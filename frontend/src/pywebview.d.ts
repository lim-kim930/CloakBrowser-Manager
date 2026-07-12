export {};

declare global {
  interface Window {
    __cbShowCloseModal?: () => void;
    pywebview?: {
      api?: {
        on_close_choice?: (choice: string, remember: boolean) => void;
        pick_folder?: () => Promise<string | null>;
      };
    };
  }
}
