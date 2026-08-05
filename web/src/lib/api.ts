/**
 * Cliente de la API de HearMe.
 *
 * El backend es la única fuente de verdad sobre qué motores y formatos existen:
 * la UI nunca codifica esa lista, la pide con `getSystem()`.
 */

import { browser } from '$app/environment';
import { env } from '$env/dynamic/public';

/**
 * URL de la API, resuelta en tiempo de ejecución.
 *
 * Antes era `import.meta.env.PUBLIC_API_URL`, que Vite solo sustituye para
 * variables con prefijo `VITE_`: la expresión valía `undefined` y el bundle se
 * compilaba con `http://127.0.0.1:8000` incrustado. Consecuencias: la variable
 * `PUBLIC_API_URL` del contenedor `web` no hacía nada, y abrir la interfaz desde
 * otro equipo de la red apuntaba al `localhost` *del visitante*, no al servidor.
 *
 * `$env/dynamic/public` sí se lee al arrancar. Sin ella, se deduce del host por
 * el que se está navegando, que es lo correcto en una LAN.
 */
function resolveApiUrl(): string {
	if (env.PUBLIC_API_URL) return env.PUBLIC_API_URL.replace(/\/$/, '');
	if (browser) return `${location.protocol}//${location.hostname}:8000`;
	return 'http://127.0.0.1:8000';
}

export const API_URL = resolveApiUrl();

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Job {
	id: string;
	status: JobStatus;
	source_path: string;
	title: string;
	mode: string;
	stage: string;
	progress: number;
	error: string | null;
	outputs: string[];
	duration_s: number;
	engine: string | null;
	voice: string | null;
	language: string | null;
	attempts: number;
	created_at: string | null;
	updated_at: string | null;
}

export interface TTSEngineInfo {
	name: string;
	available: boolean;
	languages: string[];
	naturalness: number;
	rtf: number;
	non_commercial: boolean;
}

export interface SystemInfo {
	version: string;
	/** Capacidad del servicio. Dato de operación: la lectura no depende de él. */
	runtime: {
		accelerator: string;
		synthesis_workers: number;
		languages: string[];
	};
	parsers: string[];
	tts_engines: TTSEngineInfo[];
	exporters: string[];
	translators: string[];
	ocr: string[];
	warnings: string[];
}

export interface ConversionOptions {
	mode?: string;
	formats?: string[];
	language?: string | null;
	target_language?: string | null;
	engine?: string | null;
	voice?: string | null;
	style?: string;
	quality?: string;
	ocr?: boolean | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API_URL}${path}`, init);
	if (!response.ok) {
		let detail = response.statusText;
		try {
			detail = (await response.json()).detail ?? detail;
		} catch {
			// respuesta sin cuerpo JSON: nos quedamos con statusText
		}
		throw new Error(detail);
	}
	return response.json() as Promise<T>;
}

export const getSystem = () => request<SystemInfo>('/api/system');

export const listJobs = (limit = 50) => request<Job[]>(`/api/jobs?limit=${limit}`);

export const getJob = (id: string) => request<Job>(`/api/jobs/${id}`);

export const cancelJob = (id: string) =>
	request<{ cancelled: boolean }>(`/api/jobs/${id}`, { method: 'DELETE' });

export async function convert(
	file: File,
	options: ConversionOptions
): Promise<{ job_id: string; status: string }> {
	const body = new FormData();
	body.append('file', file);
	body.append('options', JSON.stringify(options));
	return request('/api/convert', { method: 'POST', body });
}

export const downloadUrl = (jobId: string, index: number) =>
	`${API_URL}/api/jobs/${jobId}/download/${index}`;

export interface ProgressEvent {
	type: string;
	stage?: string;
	current?: number;
	total?: number;
	detail?: string;
	error?: string;
	outputs?: string[];
}

/**
 * Suscripción SSE al progreso de un trabajo.
 * Devuelve la función de cierre; llamarla es obligatorio al desmontar.
 */
export function subscribeToJob(
	jobId: string,
	onEvent: (event: ProgressEvent) => void
): () => void {
	const source = new EventSource(`${API_URL}/api/jobs/${jobId}/events`);

	source.onmessage = (message) => {
		try {
			onEvent(JSON.parse(message.data) as ProgressEvent);
		} catch {
			// Un evento malformado no debe romper el stream entero.
		}
	};
	// El backend cierra el stream al terminar; EventSource reintentaría en bucle.
	source.onerror = () => source.close();

	return () => source.close();
}

export function formatDuration(seconds: number): string {
	const total = Math.round(seconds);
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	return h > 0
		? `${h}h ${String(m).padStart(2, '0')}m`
		: `${m}m ${String(s).padStart(2, '0')}s`;
}
