# Frontend

Frontend bootstrap for ProxyMind.

## Stack

- React 19
- Vite 8
- TypeScript 5.9
- Biome 2.4.7 for linting and formatting

## Scripts

```bash
bun install
bun run dev
bun run lint
bun run format
bun run build
```

## Environment

Create the local environment file once:

```bash
cp .env.example .env
```

Supported variables:

- `VITE_API_URL`: backend base URL for local development

## Notes

- Biome is the only formatter and linter in this package.
- ESLint and Prettier are intentionally not used here.
