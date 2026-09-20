import { expect, test } from '@playwright/test'

// Full user journey on the real built SPA + fake provider (M1c-2b 2b-5):
// start a run from the form, watch the provenance DAG arrive, resolve Gate A and
// scrub the timeline with Replay.
test('start a run, see the DAG, resolve Gate A and replay', async ({ page }) => {
  await page.goto('/projects/e2e/runs/new')

  await page.getByLabel('source text').fill('Copilot cut task time by 55%.')
  await page.getByLabel('goal').fill('Every claim is sourced.')
  await page.getByRole('button', { name: '创建并进入审阅台' }).click()

  // The console mounts and the DAG grows as the run progresses (the run polls
  // itself while it is still active).
  await expect(page.getByLabel('run console')).toBeVisible()
  await expect(page.getByTestId(/^fact-node-/).first()).toBeVisible()

  // Gate A: confirm the core claim, then the run resumes.
  const approve = page.getByRole('button', { name: 'approve' })
  await expect(approve).toBeEnabled()
  await approve.click()

  // Replay: step back into the folded board, then return to live.
  await expect(page.locator('.replay-step')).toHaveText('live')
  await page.getByRole('button', { name: 'replay back' }).click()
  await expect(page.locator('.replay-step')).toHaveText(/\d+\/\d+/)
  await page.getByRole('button', { name: 'replay live' }).click()
  await expect(page.locator('.replay-step')).toHaveText('live')
})
