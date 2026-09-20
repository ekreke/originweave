// Process-level watchdog around `vitest run`. Vitest's own testTimeout relies on timers,
// so a test that spins in microtasks (e.g. a self-resuming promise chain) starves the
// event loop and can never be interrupted from inside — a hung worker then burns CPU
// forever. This wrapper runs vitest in its own process group and SIGKILLs the whole
// group when the deadline passes. Timeout is seconds, default 300. The negative-pid kill
// is POSIX-only (fine for macOS dev and the ubuntu CI; on Windows workers could survive).
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const raw = process.env.VITEST_WATCHDOG_TIMEOUT
const timeoutSeconds = raw === undefined ? 300 : Number(raw)
if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
  console.error(`[vitest-watchdog] invalid VITEST_WATCHDOG_TIMEOUT: ${JSON.stringify(raw)}`)
  process.exit(1)
}
const timeoutMs = timeoutSeconds * 1000
const vitestEntry = fileURLToPath(new URL('../node_modules/vitest/vitest.mjs', import.meta.url))

const child = spawn(process.execPath, [vitestEntry, 'run', ...process.argv.slice(2)], {
  stdio: 'inherit',
  detached: true,
})

const watchdog = setTimeout(() => {
  console.error(
    `\n[vitest-watchdog] tests exceeded ${timeoutSeconds}s; killing the vitest process group.\n` +
      '[vitest-watchdog] testTimeout cannot interrupt a timer-starving spin; fix the looping test.',
  )
  try {
    process.kill(-child.pid, 'SIGKILL')
  } catch {
    child.kill('SIGKILL')
  }
}, timeoutMs)

child.on('error', (error) => {
  clearTimeout(watchdog)
  console.error(`[vitest-watchdog] failed to start vitest: ${error.message}`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  clearTimeout(watchdog)
  process.exit(code ?? (signal ? 1 : 0))
})
