use std::fs;
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const DEFAULT_PORT: u16 = 8000;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Clone, Serialize)]
pub struct BackendSnapshot {
    pub state: String, // "starting" | "port-conflict" | "ready" | "error"
    pub port: u16,
    pub message: Option<String>,
}

impl Default for BackendSnapshot {
    fn default() -> Self {
        Self { state: "starting".into(), port: DEFAULT_PORT, message: None }
    }
}

#[derive(Default)]
pub struct BackendState {
    snapshot: Mutex<BackendSnapshot>,
    child: Mutex<Option<CommandChild>>,
    child_exited: Arc<AtomicBool>,
    shutting_down: Arc<AtomicBool>,
}

#[derive(Serialize, Deserialize)]
struct AppConfig {
    port: u16,
}

fn config_path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_config_dir()
        .expect("app_config_dir unavailable")
        .join("config.json")
}

fn read_port(app: &AppHandle) -> u16 {
    fs::read_to_string(config_path(app))
        .ok()
        .and_then(|s| serde_json::from_str::<AppConfig>(&s).ok())
        .map(|c| c.port)
        .unwrap_or(DEFAULT_PORT)
}

fn write_port(app: &AppHandle, port: u16) -> Result<(), String> {
    let path = config_path(app);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(&AppConfig { port }).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}

pub fn port_is_free(port: u16) -> bool {
    // Bind, not connect: the backend needs to BIND this port, and binding
    // also detects TIME_WAIT leftovers that a connect probe would miss.
    TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port)).is_ok()
}

/// Update the shared snapshot and broadcast it as an event. The frontend
/// also pulls the snapshot via get_backend_state on startup, so events
/// emitted before its listeners attach are never lost.
fn set_snapshot(app: &AppHandle, state: &str, port: u16, message: Option<String>) {
    let snap = BackendSnapshot { state: state.into(), port, message };
    {
        let st = app.state::<BackendState>();
        *st.snapshot.lock().unwrap() = snap.clone();
    }
    let event = match state {
        "port-conflict" => "port-conflict",
        "ready" => "backend-ready",
        "error" => "backend-error",
        _ => "backend-starting",
    };
    let _ = app.emit(event, snap);
}

fn spawn_backend(app: &AppHandle, port: u16) -> Result<CommandChild, String> {
    let port_arg = port.to_string();

    let cmd = if cfg!(debug_assertions) {
        // Dev: run the Python backend from source so `tauri dev` doesn't
        // require a PyInstaller build on every iteration.
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")); // .../frontend/src-tauri
        let repo_root = manifest
            .parent()
            .and_then(|p| p.parent())
            .expect("repo root")
            .to_path_buf();
        let venv_python = repo_root.join("backend/.venv/Scripts/python.exe");
        let python = if venv_python.exists() {
            venv_python.to_string_lossy().into_owned()
        } else {
            "python".to_string()
        };
        app.shell()
            .command(python)
            .args(["-m", "backend.main", "--port", &port_arg])
            .current_dir(repo_root)
    } else {
        app.shell()
            .sidecar("server")
            .map_err(|e| e.to_string())?
            .args(["--port", &port_arg])
    };

    // stdin stays piped and open for the child's lifetime — it closing is the
    // backend's watchdog signal to shut itself down if this shell dies.
    let (mut rx, child) = cmd.spawn().map_err(|e| e.to_string())?;

    let state = app.state::<BackendState>();
    state.child_exited.store(false, Ordering::SeqCst);
    let exited = state.child_exited.clone();
    let shutting_down = state.shutting_down.clone();

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    println!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    exited.store(true, Ordering::SeqCst);
                    if !shutting_down.load(Ordering::SeqCst) {
                        let port = app_handle
                            .state::<BackendState>()
                            .snapshot
                            .lock()
                            .unwrap()
                            .port;
                        set_snapshot(
                            &app_handle,
                            "error",
                            port,
                            Some(format!("backend exited unexpectedly (code {:?})", payload.code)),
                        );
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(child)
}

/// Full startup flow: read configured port → probe → spawn → poll health.
/// Runs on its own thread; progress lands in the snapshot + events.
pub fn start_backend(app: AppHandle) {
    std::thread::spawn(move || {
        let port = read_port(&app);
        set_snapshot(&app, "starting", port, None);

        if !port_is_free(port) {
            set_snapshot(&app, "port-conflict", port, None);
            return;
        }

        let child = match spawn_backend(&app, port) {
            Ok(c) => c,
            Err(e) => {
                set_snapshot(&app, "error", port, Some(format!("failed to spawn backend: {e}")));
                return;
            }
        };
        {
            let state = app.state::<BackendState>();
            *state.child.lock().unwrap() = Some(child);
        }

        let url = format!("http://127.0.0.1:{port}/api/health");
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        loop {
            if app.state::<BackendState>().child_exited.load(Ordering::SeqCst) {
                return; // Terminated handler already reported the error
            }
            if Instant::now() > deadline {
                set_snapshot(
                    &app,
                    "error",
                    port,
                    Some("backend did not become healthy within 30s".into()),
                );
                return;
            }
            match ureq::get(&url).timeout(Duration::from_secs(2)).call() {
                Ok(resp) if resp.status() == 200 => break,
                _ => std::thread::sleep(Duration::from_millis(500)),
            }
        }
        set_snapshot(&app, "ready", port, None);
    });
}

/// Graceful teardown: POST /api/shutdown (backend closes every browser
/// context so session data flushes), wait up to 10s, then hard-kill.
fn shutdown_backend(app: &AppHandle) {
    let state = app.state::<BackendState>();
    state.shutting_down.store(true, Ordering::SeqCst);
    let child = state.child.lock().unwrap().take();
    let Some(child) = child else { return };

    let port = state.snapshot.lock().unwrap().port;
    let _ = ureq::post(&format!("http://127.0.0.1:{port}/api/shutdown"))
        .timeout(Duration::from_secs(3))
        .send_string("");

    let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
    while Instant::now() < deadline {
        if state.child_exited.load(Ordering::SeqCst) {
            return;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    println!("[shell] backend did not exit in time — killing");
    let _ = child.kill();
}

#[tauri::command]
fn probe_port(port: u16) -> bool {
    port_is_free(port)
}

#[tauri::command]
fn get_backend_state(state: State<'_, BackendState>) -> BackendSnapshot {
    state.snapshot.lock().unwrap().clone()
}

#[tauri::command]
async fn save_port(app: AppHandle, port: u16) -> Result<(), String> {
    write_port(&app, port)?;
    restart_backend(app).await
}

#[tauri::command]
async fn restart_backend(app: AppHandle) -> Result<(), String> {
    // Async command → runs off the main thread; blocking here is fine.
    shutdown_backend(&app);
    let state = app.state::<BackendState>();
    state.shutting_down.store(false, Ordering::SeqCst);
    start_backend(app.clone());
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Second launch: focus the existing window instead.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState::default())
        .invoke_handler(tauri::generate_handler![
            probe_port,
            get_backend_state,
            save_port,
            restart_backend
        ])
        .setup(|app| {
            start_backend(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                shutdown_backend(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_detects_bound_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(!port_is_free(port));
        drop(listener);
        assert!(port_is_free(port));
    }
}
