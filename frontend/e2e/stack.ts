export interface StackLifecycleOptions {
  ci: boolean;
  fresh?: boolean;
}

export interface IsolatedStackConfig {
  apiService: string;
  backendTestService: string;
  backendUrl: string;
  composeFiles: string[];
  frontendUrl: string;
  projectName: string;
}

const defaultConfig: IsolatedStackConfig = {
  apiService: "api-e2e",
  backendTestService: "backend-test-e2e",
  backendUrl: `http://127.0.0.1:${process.env.E2E_API_HOST_PORT ?? "18001"}`,
  composeFiles: ["docker-compose.yml", "docker-compose.e2e.yml"],
  frontendUrl: "http://127.0.0.1:4173",
  projectName: process.env.E2E_DOCKER_PROJECT ?? "proxymind-e2e",
};

export function getIsolatedStackConfig(): IsolatedStackConfig {
  return defaultConfig;
}

export function composeArgs(args: string[]) {
  const config = getIsolatedStackConfig();

  return [
    "compose",
    "-p",
    config.projectName,
    ...config.composeFiles.flatMap((file) => ["-f", file]),
    ...args,
  ];
}

export function shouldResetIsolatedStack(options: StackLifecycleOptions) {
  return options.ci || Boolean(options.fresh);
}

export function shouldTearDownIsolatedStack(options: StackLifecycleOptions) {
  return options.ci;
}
