export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const MUTATION_HEADER = { "X-MIERU-Request": "1" };

async function parseError(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  let message = `Request failed (${response.status})`;
  try {
    detail = await response.json();
    const candidate = (detail as { detail?: unknown })?.detail;
    if (typeof candidate === "string") message = candidate;
    else if (candidate && typeof candidate === "object" && "message" in candidate) {
      message = String((candidate as { message: unknown }).message);
    }
  } catch {
    message = response.statusText || message;
  }
  return new ApiError(response.status, message, detail);
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export async function sendJson<T>(path: string, method: "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { ...MUTATION_HEADER, Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export function uploadFile<T>(path: string, file: File, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", path);
    request.withCredentials = true;
    request.setRequestHeader("X-MIERU-Request", "1");
    request.setRequestHeader("Accept", "application/json");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      let payload: unknown = null;
      try {
        payload = JSON.parse(request.responseText);
      } catch {
        payload = null;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as T);
        return;
      }
      const detail = (payload as { detail?: unknown } | null)?.detail;
      const message = typeof detail === "string" ? detail : `Upload failed (${request.status})`;
      reject(new ApiError(request.status, message, payload));
    };
    request.onerror = () => reject(new ApiError(0, "Network error while uploading. Is the MIERU server running?", null));
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}
