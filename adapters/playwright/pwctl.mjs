/**
 * pwctl — browser action layer of the agent system.
 *
 * Structured rather than visual: localization via accessibility roles and
 * names, verification via DOM and HTTP response. Screenshots and pixel
 * coordinates are a fallback, not the way of working.
 *
 * Every output is JSON on stdout. Diagnostics go to stderr.
 *
 * Invocation:
 *   node C:\AgentSystem\adapters\playwright\pwctl.mjs <command> [options]
 *
 * Profiles: `--profile <name>` uses a persistent browser context under
 * `state/browser-profiles/<name>`. It contains cookies and session data and
 * is therefore a secret in the sense of AGENTS.md section 20 — it lives
 * outside version control and is never logged.
 */

import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.env.AGENTSYSTEM_ROOT || 'C:\\AgentSystem';
const PROFILE_ROOT = path.join(ROOT, 'state', 'browser-profiles');

const DEFAULT_TIMEOUT = 20000;

function out(payload) {
  process.stdout.write(JSON.stringify(payload, null, 2) + '\n');
}

function fail(message, extra = {}) {
  out({ status: 'FAILED', error: message, ...extra });
  process.exit(1);
}

function parseArgs(argv) {
  const command = argv[2];
  const options = {};
  for (let i = 3; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      options[key] = true;
    } else {
      options[key] = next;
      i += 1;
    }
  }
  return { command, options };
}

/** Opens a browser: either ephemeral or with a persistent profile. */
async function open(options, { forceHeaded = false } = {}) {
  const headless = forceHeaded ? false : (options.headed ? false : true);
  if (options.profile) {
    const dir = path.join(PROFILE_ROOT, String(options.profile));
    mkdirSync(dir, { recursive: true });
    const context = await chromium.launchPersistentContext(dir, { headless });
    const page = context.pages()[0] || (await context.newPage());
    return { context, page, close: () => context.close() };
  }
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext();
  const page = await context.newPage();
  return { context, page, close: () => browser.close() };
}

/** Loads a page and returns the HTTP response — that is verifiable. */
async function goto(page, url, options) {
  const response = await page.goto(url, {
    waitUntil: options.wait || 'domcontentloaded',
    timeout: Number(options.timeout || DEFAULT_TIMEOUT),
  });
  return response
    ? { url: response.url(), status: response.status(), ok: response.ok() }
    : { url, status: null, ok: null };
}

/** Builds a locator from role and name — the stable localization. */
function locate(page, options) {
  if (options.role) {
    const byRole = page.getByRole(options.role, {
      name: options.name,
      exact: Boolean(options.exact),
    });
    return options.nth !== undefined ? byRole.nth(Number(options.nth)) : byRole;
  }
  if (options.label) return page.getByLabel(options.label);
  if (options.placeholder) return page.getByPlaceholder(options.placeholder);
  if (options.text) return page.getByText(options.text);
  if (options.testid) return page.getByTestId(options.testid);
  if (options.selector) return page.locator(options.selector);
  throw new Error(
    'No locator specified. Prefer --role with --name; ' +
      'otherwise --label, --placeholder, --text, --testid, or as a last resort --selector.'
  );
}

/**
 * Runs a sequence of steps on an already-open page.
 *
 * Shared by `plan` and `session`. Aborts on the first failure and reports
 * what already ran - a half-executed plan is not a success.
 */
async function runSteps(page, steps) {
  const done = [];
  for (const [index, step] of (steps || []).entries()) {
    try {
      let result = null;
      if (step.action === 'goto') {
        result = await goto(page, step.url, step);
      } else if (step.action === 'wait') {
        await page.waitForTimeout(Number(step.ms || 1000));
        result = 'waited';
      } else if (step.action === 'expect') {
        const locator = locate(page, step);
        const visible = await locator.first().isVisible().catch(() => false);
        if (!visible) throw new Error('Expected element is not visible');
        result = { visible: true };
      } else {
        const locator = locate(page, step);
        if (step.action === 'click') {
          await locator.click({ timeout: Number(step.timeout || DEFAULT_TIMEOUT) });
          result = { url_after: page.url() };
        } else if (step.action === 'fill') {
          await locator.fill(String(step.value ?? ''));
          const back = await locator.inputValue().catch(() => null);
          result = { read_back: back, verified: back === String(step.value ?? '') };
        } else if (step.action === 'read') {
          result = { text: (await locator.innerText()).slice(0, 2000) };
        } else if (step.action === 'aria') {
          const snap = await locator.ariaSnapshot();
          result = { aria: snap.split('\n').slice(0, 80).join('\n') };
        } else {
          throw new Error(`Unknown action: ${step.action}`);
        }
      }
      done.push({ index, action: step.action, status: 'OK', result });
    } catch (error) {
      done.push({ index, action: step.action, status: 'FAILED', error: error.message });
      return { ok: false, done, remaining: (steps || []).length - index - 1 };
    }
  }
  return { ok: true, done, remaining: 0 };
}

/**
 * Waits until a login has observably succeeded.
 *
 * The tool **never** types a password - credentials are entered exclusively
 * by the user themselves (AGENTS.md section 20).
 */
async function waitForLogin(page, options, startUrl) {
  const deadline = Date.now() + Number(options.timeout || 300000);
  while (Date.now() < deadline) {
    await page.waitForTimeout(1500);
    try {
      if (options.until) {
        const locator = options.role
          ? page.getByRole(options.role, { name: options.until })
          : page.getByText(options.until);
        if (await locator.first().isVisible().catch(() => false)) return true;
      } else if (page.url() !== startUrl) {
        return true;
      }
    } catch {
      // Navigation mid-check: next iteration.
    }
  }
  return false;
}

// ---------------------------------------------------------------------------

const COMMANDS = {
  /**
   * Accessibility snapshot: the structured view of the page.
   *
   * Uses `ariaSnapshot`. The former `page.accessibility` no longer exists in
   * Playwright 1.62 - see docs/known-issues.md.
   */
  async snapshot({ page }, options) {
    const response = await goto(page, options.url, options);
    const scope = options.selector ? page.locator(options.selector) : page.locator('body');
    const yaml = await scope.ariaSnapshot();
    let lines = yaml.split('\n');
    if (options.role) {
      lines = lines.filter((line) => line.includes(`- ${options.role} `) ||
                                     line.trimStart().startsWith(`- ${options.role}`));
    }
    const limit = Number(options.limit || 300);
    return {
      response,
      title: await page.title(),
      line_count: lines.length,
      truncated: lines.length > limit,
      aria: lines.slice(0, limit).join('\n'),
    };
  },

  /**
   * Login mode: opens the page visibly and waits until YOU have logged in.
   * The tool **never** types a password — credentials are entered
   * exclusively by the user themselves (AGENTS.md section 20).
   *
   * Success is tied to an observable state: an expected role, a text, or a
   * URL change. Only once that occurs does the login count as confirmed.
   */
  async login({ page }, options) {
    const response = await goto(page, options.url, options);
    const deadline = Date.now() + Number(options.timeout || 300000);
    const startUrl = page.url();

    let reached = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(1500);
      try {
        if (options.until) {
          const locator = options.role
            ? page.getByRole(options.role, { name: options.until })
            : page.getByText(options.until);
          if (await locator.first().isVisible().catch(() => false)) { reached = true; break; }
        } else if (page.url() !== startUrl) {
          reached = true;
          break;
        }
      } catch {
        // Navigation mid-check: next iteration.
      }
    }

    const aria = await page.locator('body').ariaSnapshot().catch(() => '');
    return {
      response,
      profile: options.profile || null,
      logged_in: reached,
      url_after: page.url(),
      title_after: await page.title().catch(() => null),
      hint: reached
        ? 'Session lives in the profile and persists for further calls.'
        : 'No successful login detected. Either you did not log in, or the '
          + 'success criterion (--until) does not match the interface.',
      aria: aria.split('\n').slice(0, 60).join('\n'),
    };
  },

  /** Plain page text — for diagnostics and content checks. */
  async text({ page }, options) {
    const response = await goto(page, options.url, options);
    const target = options.selector ? page.locator(options.selector) : page.locator('body');
    const content = (await target.innerText()).trim();
    const limit = Number(options.limit || 6000);
    return {
      response,
      title: await page.title(),
      truncated: content.length > limit,
      text: content.slice(0, limit),
    };
  },

  /** HTTP response without interaction — the cheapest verification. */
  async http({ page }, options) {
    const response = await goto(page, options.url, options);
    return { response, title: await page.title() };
  },

  async click({ page }, options) {
    const response = await goto(page, options.url, options);
    const locator = locate(page, options);
    const count = await locator.count();
    if (count === 0) throw new Error('No element found for the locator');
    if (count > 1 && options.nth === undefined) {
      throw new Error(
        `Locator matches ${count} elements. Narrow down with --nth or ` +
          'set --exact, instead of guessing and taking the first one.'
      );
    }
    await locator.click({ timeout: Number(options.timeout || DEFAULT_TIMEOUT) });
    await page.waitForLoadState(options.wait || 'domcontentloaded').catch(() => {});
    return {
      response,
      clicked: { role: options.role, name: options.name, selector: options.selector },
      url_after: page.url(),
      title_after: await page.title(),
    };
  },

  /** Fill a field and read the value back — written only counts once verified. */
  async fill({ page }, options) {
    const response = await goto(page, options.url, options);
    const locator = locate(page, options);
    if ((await locator.count()) === 0) throw new Error('No input field found');
    await locator.fill(String(options.value ?? ''), {
      timeout: Number(options.timeout || DEFAULT_TIMEOUT),
    });
    const readBack = await locator.inputValue().catch(() => null);
    return {
      response,
      filled: { role: options.role, name: options.name, selector: options.selector },
      read_back: readBack,
      verified: readBack === String(options.value ?? ''),
    };
  },

  /** Screenshot — explicitly a fallback, not the way of working. */
  async screenshot({ page }, options) {
    const response = await goto(page, options.url, options);
    const target = options.out || path.join(ROOT, 'logs', `screenshot-${Date.now()}.png`);
    mkdirSync(path.dirname(target), { recursive: true });
    await page.screenshot({ path: target, fullPage: Boolean(options.full) });
    return { response, screenshot: target };
  },

  /**
   * Sequence of steps in one context. Aborts on the first failure and
   * reports what already ran — a half-executed plan is not a success.
   */
  async plan({ page }, options) {
    const plan = JSON.parse(await readFile(options.file, 'utf-8'));
    let response = null;
    if (plan.url) response = await goto(page, plan.url, options);
    const run = await runSteps(page, plan.steps);
    return {
      status: run.ok ? 'OK' : 'FAILED',
      response,
      completed_steps: run.done,
      remaining: run.remaining,
      url_after: page.url(),
    };
  },
};

// ---------------------------------------------------------------------------

const { command, options } = parseArgs(process.argv);

if (!command || command === 'help' || !COMMANDS[command]) {
  out({
    commands: Object.keys(COMMANDS),
    locators: ['--role + --name (preferred)', '--label', '--placeholder', '--text',
               '--testid', '--selector (last resort)'],
    common: ['--url', '--profile', '--headed', '--timeout', '--wait', '--nth', '--exact'],
    login: 'opens the page visibly and waits until YOU have logged in. '
         + 'The tool never types a password. Use --until <text> to specify the '
         + 'success criterion, otherwise a URL change counts as success.',
    note: 'Screenshots and selectors are a fallback. Accessibility roles are stable.',
  });
  process.exit(command && command !== 'help' ? 1 : 0);
}

if (!options.url && command !== 'plan') {
  fail('--url missing');
}

let session;
try {
  session = await open(options, { forceHeaded: command === 'login' });
  const result = await COMMANDS[command](session, options);
  out(result);
} catch (error) {
  fail(error.message, { command });
} finally {
  if (session) await session.close().catch(() => {});
}
