import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';

const BASE = process.env.MAP_E2E_BASE || 'http://127.0.0.1:3001';
const SHOTS = process.env.MAP_E2E_SHOTS || 'C:/Users/KUNAL/.gemini/antigravity-ide/brain/033124ee-b8a0-4a23-ab6a-c5e484139098';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const ok = (name, cond, extra = '') => {
  results.push([cond ? 'PASS' : 'FAIL', name, extra]);
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   ' + extra : ''));
  if (!cond) throw new Error(name + ': ' + extra);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });

try {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);

  // Drive DECODE ALL TODAY or navigate to Results
  const decodeAllBtn = page.locator('button:has-text("DECODE ALL TODAY")');
  if (await decodeAllBtn.count()) {
    await decodeAllBtn.first().click().catch(() => {});
    const modalBtn = page.locator('div[role="dialog"] button:has-text("VIEW RESULTS"), div[role="dialog"] button:has-text("[ View Results ]"), div[role="dialog"] button:has-text("View Results")');
    for (let i = 0; i < 25; i++) {
      if (await modalBtn.count()) break;
      await page.waitForTimeout(300);
    }
    if (await modalBtn.count()) {
      await modalBtn.first().click().catch(() => {});
    }
  }

  const resultsBtn = page.locator('button:has-text("VIEW RESULTS"), button:has-text("Results")');
  if (await resultsBtn.count()) {
    await resultsBtn.first().click().catch(() => {});
  }

  // Click [ Expand Fleet ]
  const expandBtn = page.getByText('[ Expand Fleet ]');
  await expandBtn.waitFor({ timeout: 15000 });
  await expandBtn.click();
  await page.waitForTimeout(1000);

  // 1. Verify floating fleet-info panel exists
  const panel = page.locator('[data-testid="fleet-info-panel"]');
  await panel.waitFor({ timeout: 5000 });
  ok('1. floating fleet-info panel rendered in Expand Fleet mode', await panel.isVisible());

  // Take screenshot of initial Expand Fleet view
  await page.screenshot({ path: path.join(SHOTS, 'expand_fleet_initial.png') });

  // 2. Verify drag handle exists and has cursor-ns-resize
  const dragHandle = page.locator('[data-testid="fleet-panel-drag-handle"]');
  await dragHandle.waitFor({ timeout: 5000 });
  const cursor = await dragHandle.evaluate((el) => window.getComputedStyle(el).cursor);
  ok('2. drag handle exists with cursor-ns-resize affordance', (await dragHandle.isVisible()) && cursor === 'ns-resize', `cursor=${cursor}`);

  // 3. Initial panel dimensions
  const initBox = await panel.boundingBox();
  ok('3. panel has valid initial height', Boolean(initBox && initBox.height >= 180), `height=${initBox?.height}`);

  // 4. Count initially visible float rows in table
  const rows = panel.locator('tbody tr');
  const rowCount = await rows.count();
  ok('4. fleet table contains float rows', rowCount > 0, `rows=${rowCount}`);

  // 5. Drag the handle upward by 180px
  const handleBox = await dragHandle.boundingBox();
  const startX = handleBox.x + handleBox.width / 2;
  const startY = handleBox.y + handleBox.height / 2;
  const dragDistance = 180;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX, startY - dragDistance, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(400);

  // Take screenshot of expanded view with more rows revealed
  await page.screenshot({ path: path.join(SHOTS, 'expand_fleet_dragged_up.png') });

  // Verify panel expanded upward
  const newBox = await panel.boundingBox();
  const heightDiff = newBox.height - initBox.height;
  ok('5. panel height expands when dragged upward', heightDiff >= 140, `expanded from ${initBox.height} to ${newBox.height} (+${heightDiff}px)`);

  // 6. Verify scrolling inside table is preserved
  const tableContainer = panel.locator('.overflow-y-auto');
  const scrollable = await tableContainer.evaluate((el) => {
    const prev = el.scrollTop;
    el.scrollTop = 100;
    const moved = el.scrollTop > 0;
    el.scrollTop = prev;
    return moved;
  });
  ok('6. internal scrolling inside panel table is preserved', scrollable || rowCount <= 5, 'scrolling functional');

  // 7. Verify position stays stable during interaction (switching filters)
  const successTab = panel.getByRole('button', { name: /^SUCCESS/ });
  if (await successTab.count()) {
    await successTab.click();
    await page.waitForTimeout(300);
    const afterFilterBox = await panel.boundingBox();
    const diff = Math.abs(afterFilterBox.height - newBox.height);
    ok('7. panel height remains stable while interacting with filters', diff < 5, `height=${afterFilterBox.height}`);
  }

  // 8. Drag downward to shrink
  const handleBox2 = await dragHandle.boundingBox();
  await page.mouse.move(handleBox2.x + handleBox2.width / 2, handleBox2.y + handleBox2.height / 2);
  await page.mouse.down();
  await page.mouse.move(handleBox2.x + handleBox2.width / 2, handleBox2.y + handleBox2.height / 2 + 100, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const shrunkenBox = await panel.boundingBox();
  ok('8. panel shrinks when dragged downward', shrunkenBox.height < newBox.height, `height=${shrunkenBox.height}`);

  // 9. Exit full-screen
  await page.getByText('[ Exit Full Screen ]').click();
  await page.waitForTimeout(500);
  const dragHandleAfterExit = await page.locator('[data-testid="fleet-panel-drag-handle"]').count();
  ok('9. drag handle hidden when exiting full screen (normal layout restored)', dragHandleAfterExit === 0);

  console.log('\nALL DRAG E2E TESTS PASSED SUCCESSFULLY!');
} finally {
  await browser.close();
}
