/**
 * pwctl — Browser-Aktionsschicht des Agentensystems.
 *
 * Strukturiert statt visuell: Lokalisierung über Accessibility-Rollen und
 * -Namen, Verifikation über DOM und HTTP-Antwort. Screenshots und
 * Pixelkoordinaten sind Fallback, nicht Arbeitsweise.
 *
 * Jede Ausgabe ist JSON auf stdout. Diagnose geht nach stderr.
 *
 * Aufruf:
 *   node C:\AgentSystem\adapters\playwright\pwctl.mjs <befehl> [optionen]
 *
 * Profile: `--profile <name>` benutzt einen persistenten Browserkontext unter
 * `state/browser-profiles/<name>`. Der enthält Cookies und Sitzungsdaten und
 * ist damit ein Secret im Sinne von AGENTS.md Abschnitt 20 — er liegt
 * ausserhalb der Versionskontrolle und wird nie protokolliert.
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

/** Öffnet einen Browser: entweder flüchtig oder mit persistentem Profil. */
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

/** Lädt eine Seite und gibt die HTTP-Antwort zurück — die ist verifizierbar. */
async function goto(page, url, options) {
  const response = await page.goto(url, {
    waitUntil: options.wait || 'domcontentloaded',
    timeout: Number(options.timeout || DEFAULT_TIMEOUT),
  });
  return response
    ? { url: response.url(), status: response.status(), ok: response.ok() }
    : { url, status: null, ok: null };
}

/** Baut einen Locator aus Rolle und Name — die stabile Lokalisierung. */
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
    'Kein Lokalisierer angegeben. Bevorzugt --role mit --name; ' +
      'sonst --label, --placeholder, --text, --testid oder als letztes --selector.'
  );
}

/**
 * Führt eine Schrittfolge auf einer bereits geöffneten Seite aus.
 *
 * Gemeinsam genutzt von `plan` und `session`. Bricht beim ersten Fehlschlag ab
 * und meldet, was bereits lief - ein halb ausgeführter Plan ist kein Erfolg.
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
        result = 'gewartet';
      } else if (step.action === 'expect') {
        const locator = locate(page, step);
        const visible = await locator.first().isVisible().catch(() => false);
        if (!visible) throw new Error('Erwartetes Element ist nicht sichtbar');
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
          throw new Error(`Unbekannte Aktion: ${step.action}`);
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
 * Wartet, bis eine Anmeldung beobachtbar gelungen ist.
 *
 * Das Werkzeug tippt **kein** Passwort - Zugangsdaten gibt ausschliesslich der
 * Benutzer selbst ein (AGENTS.md Abschnitt 20).
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
      // Navigation mitten in der Prüfung: nächster Durchlauf.
    }
  }
  return false;
}

// ---------------------------------------------------------------------------

const COMMANDS = {
  /**
   * Accessibility-Momentaufnahme: die strukturierte Sicht auf die Seite.
   *
   * Benutzt `ariaSnapshot`. Das frühere `page.accessibility` gibt es in
   * Playwright 1.62 nicht mehr - siehe docs/known-issues.md.
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
   * Anmeldemodus: öffnet die Seite sichtbar und wartet, bis DU dich angemeldet
   * hast. Das Werkzeug tippt **kein** Passwort — Zugangsdaten gibt
   * ausschliesslich der Benutzer selbst ein (AGENTS.md Abschnitt 20).
   *
   * Erfolg wird an einem beobachtbaren Zustand festgemacht: einer erwarteten
   * Rolle, einem Text oder einem URL-Wechsel. Erst wenn der eintritt, gilt die
   * Anmeldung als bestätigt.
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
        // Navigation mitten in der Prüfung: nächster Durchlauf.
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
        ? 'Sitzung liegt im Profil und bleibt für weitere Aufrufe erhalten.'
        : 'Kein Anmeldeerfolg erkannt. Entweder wurde nicht angemeldet, oder das '
          + 'Erfolgsmerkmal (--until) passt nicht zur Oberfläche.',
      aria: aria.split('\n').slice(0, 60).join('\n'),
    };
  },

  /** Reiner Seitentext — für Diagnose und Inhaltsprüfung. */
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

  /** HTTP-Antwort ohne Interaktion — die günstigste Verifikation. */
  async http({ page }, options) {
    const response = await goto(page, options.url, options);
    return { response, title: await page.title() };
  },

  async click({ page }, options) {
    const response = await goto(page, options.url, options);
    const locator = locate(page, options);
    const count = await locator.count();
    if (count === 0) throw new Error('Kein Element gefunden für den Lokalisierer');
    if (count > 1 && options.nth === undefined) {
      throw new Error(
        `Lokalisierer trifft ${count} Elemente. Mit --nth eingrenzen oder ` +
          '--exact setzen, statt auf gut Glück das erste zu nehmen.'
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

  /** Feld füllen und den Wert zurücklesen — geschrieben gilt erst als gesetzt. */
  async fill({ page }, options) {
    const response = await goto(page, options.url, options);
    const locator = locate(page, options);
    if ((await locator.count()) === 0) throw new Error('Kein Eingabefeld gefunden');
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

  /** Screenshot — ausdrücklich Fallback, nicht Arbeitsweise. */
  async screenshot({ page }, options) {
    const response = await goto(page, options.url, options);
    const target = options.out || path.join(ROOT, 'logs', `screenshot-${Date.now()}.png`);
    mkdirSync(path.dirname(target), { recursive: true });
    await page.screenshot({ path: target, fullPage: Boolean(options.full) });
    return { response, screenshot: target };
  },

  /**
   * Schrittfolge in einem Kontext. Bricht beim ersten Fehlschlag ab und meldet,
   * was bereits lief — ein halb ausgeführter Plan ist kein Erfolg.
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
    locators: ['--role + --name (bevorzugt)', '--label', '--placeholder', '--text',
               '--testid', '--selector (letzte Wahl)'],
    common: ['--url', '--profile', '--headed', '--timeout', '--wait', '--nth', '--exact'],
    login: 'oeffnet die Seite sichtbar und wartet, bis DU dich angemeldet hast. '
         + 'Das Werkzeug tippt niemals ein Passwort. Mit --until <text> das '
         + 'Erfolgsmerkmal angeben, sonst gilt ein URL-Wechsel als Erfolg.',
    note: 'Screenshots und Selektoren sind Fallback. Accessibility-Rollen sind stabil.',
  });
  process.exit(command && command !== 'help' ? 1 : 0);
}

if (!options.url && command !== 'plan') {
  fail('--url fehlt');
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
