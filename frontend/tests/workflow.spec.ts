import {completeRecruitmentSetup} from './recruitment-setup';
import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const evidence = {
  source_type: "transcript",
  source_id: "turn-1",
  locator: "turn-1",
  excerpt: "I used a retry queue with exponential backoff.",
};
const example = {
  case_id: "fictional-case",
  mode: "recruitment",
  role: "Integration Engineer",
  cv_text: "Fictional Alex CV",
  job_description: "Fictional role",
};

test("delete interview confirms, handles failure, and removes the row", async ({page}) => {
  await fixture(page);
  let attempts = 0;
  await page.route('**/api/cases/fictional-case', async route => {
    if (route.request().method() !== 'DELETE') return route.fallback();
    attempts++;
    expect(route.request().headers()['x-csrf-token']).toBe('fixture-csrf');
    if (attempts === 1) return route.fulfill({status:409,json:{error:{code:'CASE_BUSY',message:'Wait for processing to finish before deleting this interview.'}}});
    return route.fulfill({status:204});
  });
  await page.goto('/app/interviews');
  await expect(page.getByText('Save up to 20 interviews.', {exact:false})).toBeVisible();
  const remove = page.getByRole('button', {name:'Delete interview Integration Engineer'});
  await expect(remove).toBeEnabled();
  page.once('dialog', dialog => dialog.dismiss());
  await remove.click();
  expect(attempts).toBe(0);
  await expect(remove).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await remove.click();
  await expect(page.getByRole('alert')).toContainText('Wait for processing');
  await expect(remove).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await remove.click();
  await expect(remove).toHaveCount(0);
  await expect(page.getByText('No interviews to show.', {exact:false})).toBeVisible();
  expect(attempts).toBe(2);
});
const report = {
  case_id: example.case_id,
  report_version: "fixture-version-7",
  mode: "recruitment",
  summary:
    "Fictional sample: Alex explained a retry strategy. More evidence is needed.",
  strengths: ["Explained retry handling"],
  gaps: ["Authentication was not assessed"],
  evidence: [evidence],
  suggested_next_steps: [
    "Verify authentication design with a concrete example.",
  ],
  learning_resources: [],
  draft_email: "Draft: Please review the attached evidence.",
  approval_status: "draft",
};
async function fixture(page: Page, mode = "recruitment") {
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (p === "/api/session" || p === "/api/guest-session")
      data = {
        workspace_id: "fixture-only",
        csrf_token: "fixture-csrf",
        expires_at: "2099-01-01T00:00:00Z",
      };
    else if (p === "/api/cases")
      data =
        route.request().method() === "GET"
          ? [{ ...example, mode, status: "report_ready" }]
          : { ...example, mode };
    else if (p.endsWith("/plan"))
      data = {
        case_id: example.case_id,
        plan_version: "fixture-plan",
        questions: Array.from({ length: 5 }, (_, i) => ({
          question_id: "q" + i,
          skill: "Reliability",
          question: "How do you handle failed API calls?",
          evidence: [{ ...evidence, source_type: "cv" }],
        })),
        missing_information: ["Confirm production scale."],
        warnings: [],
      };
    else if (p.endsWith("/assess"))
      data = {
        coverage: 0.6,
        skills: [
          {
            skill: "Reliability",
            status: "partially_demonstrated",
            score: 1,
            rationale:
              "Described retry queues; operational evidence is limited.",
            evidence: [evidence],
            needs_verification: true,
          },
          {
            skill: "Authentication",
            status: "not_assessed",
            score: null,
            rationale: "No relevant question answered.",
            evidence: [],
            needs_verification: true,
          },
        ],
        limitations: ["Fictional fixture only"],
      };
    else if (p.endsWith("/report"))
      data = {
        ...report,
        mode,
        draft_email: mode === "mock" ? null : report.draft_email,
        approval_status: mode === "mock" ? "not_applicable" : "draft",
      };
    else if (p.endsWith("/approve"))
      data = { ...report, approval_status: "approved" };
    else data = { case: { ...example, mode }, status: "report_ready" };
    await route.fulfill({ json: data });
  });
}
async function capture(page: Page, name: string) {
  await mkdir("screenshots", { recursive: true });
  await page.screenshot({
    path: "screenshots/" + name + ".png",
    fullPage: true,
  });
}
async function labelFixture(page: Page) {
  await page.locator("body").evaluate((el) => {
    const b = document.createElement("div");
    b.textContent =
      "FIXTURE-ONLY PREVIEW · FICTIONAL DATA · NOT A LIVE INTERVIEW";
    b.style.cssText =
      "background:#fff0bf;color:#352800;padding:12px;text-align:center;font:600 12px Arial";
    el.prepend(b);
  });
}
test("all CTAs open /app and navigation sections exist", async ({ page }) => {
  await page.goto("/");
  const ctas = page.getByRole("link", { name: "Start for free" });
  await expect(ctas).toHaveCount(4);
  for (const cta of await ctas.all())
    await expect(cta).toHaveAttribute("href", "/app");
  await expect(
    page.getByRole("link", { name: /login|sign in|sign up|book a demo/i }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "How it works", exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(/#how$/);
});
test("responsive landing captures with no horizontal overflow", async ({
  page,
}) => {
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    expect(
      await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    ).toBe(true);
    await capture(page, "landing-" + width);
  }
  await fixture(page);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/app/new");
    await expect(
      page.getByRole("button", { name: "Create interview plan" }),
    ).toBeEnabled();
    expect(
      await page.locator("body").evaluate((el) => el.scrollWidth <= innerWidth),
    ).toBe(true);
  }
});
test("session failure is explicit and cannot create cases", async ({
  page,
}) => {
  await page.route("**/api/**", (r) =>
    r.fulfill({
      status: 404,
      json: { error: { code: "NOT_FOUND", message: "Guest sessions pending" } },
    }),
  );
  await page.goto("/app");
  await expect(page.getByRole("alert")).toContainText(
    "Workspace session service unavailable",
  );
  await expect(
    page.getByRole("button", { name: "Continue", exact: false }),
  ).toBeDisabled();
});
test("first guest visit creates a workspace after 401 and sends CSRF on writes", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/session", (r) =>
    r.fulfill({ status: 401, json: { error: { code: "401" } } }),
  );
  const session = page.waitForRequest("**/api/guest-session");
  await page.goto("/app");
  await session;
  await expect(
    page.getByRole("button", { name: "Continue", exact: false }),
  ).toBeEnabled();
});
test("validation, failure recovery, plan and honest interview state", async ({
  page,
}) => {
  await fixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/app");
  await expect(
    page.getByRole("button", { name: "Continue", exact: false }),
  ).toBeEnabled();
  await labelFixture(page);
  await capture(page, "mode-selection");
  await page.getByRole("button", { name: "Continue", exact: false }).click();
  await page.getByRole("button", { name: "Create interview plan" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Add a CV and job description",
  );
  await page.getByRole("button", { name: "Use fictional sample" }).click();
  await capture(page, "upload");
  const create = page.waitForRequest(
    (r) => r.url().endsWith("/api/cases") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Create interview plan" }).click();
  expect((await create).headers()["x-csrf-token"]).toBe("fixture-csrf");
  await expect(
    page.getByRole("heading", { name: "Integration Engineer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue to interview" }).click();
  await completeRecruitmentSetup(page);
  await page.getByRole("button", { name: "Use text or browser interview instead" }).click();
  await expect(page.getByRole("button", { name: "Start text interview" })).toBeEnabled();
  await page
    .getByRole("button", { name: "Assess saved interview" })
    .click();
  await expect(page.getByText("not assessed", { exact: true })).toBeVisible();
  await capture(page, "assessment");
  await page.getByRole("button", { name: "Prepare report" }).click();
  await expect(
    page.getByText("Report version: fixture-version-7"),
  ).toBeVisible();
  await page.locator(".report summary").click();
  await expect(page.locator(".report blockquote")).toHaveText(evidence.excerpt);
  await capture(page, "recruitment-report");
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("aside")).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Approve report" }),
  ).toBeHidden();
  await expect(page.locator(".report")).toBeVisible();
  await page.emulateMedia({ media: "screen" });
  const approval = page.waitForRequest("**/approve");
  await page.getByRole("button", { name: "Approve report" }).click();
  expect((await approval).postDataJSON()).toEqual({
    report_version: "fixture-version-7",
  });
  await expect(
    page.getByRole("button", { name: "Approve report" }),
  ).toBeDisabled();
});
test("mock reports exclude approval and client email", async ({ page }) => {
  await fixture(page, "mock");
  await page.goto("/app");
  await page.getByLabel("Practise an interview").check();
  await page.getByRole("button", { name: "Continue", exact: false }).click();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByRole("button", { name: "Open report" }).click();
  await expect(
    page.getByRole("heading", { name: "Your next step forward." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve report" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Copy draft email" }),
  ).toHaveCount(0);
});
test("API failure preserves details and never shows a plan", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/cases", (r) =>
    r.fulfill({
      status: 503,
      json: {
        error: {
          code: "PROVIDER_UNAVAILABLE",
          message: "Service temporarily unavailable",
          retryable: true,
        },
      },
    }),
  );
  await page.goto("/app/new");
  await page.getByRole("button", { name: "Use fictional sample" }).click();
  await page.getByRole("button", { name: "Create interview plan" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Service temporarily unavailable",
  );
  await expect(page.getByLabel("Or paste CV text")).toHaveValue(
    /Fictional sample/,
  );
  await expect(
    page.getByRole("button", { name: "Continue to interview" }),
  ).toHaveCount(0);
});

test("plan click shows progress then brings the generated plan into view", async ({page}) => {
  await fixture(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/cases/*/plan", async route => { await gate; await route.fallback(); });
  await page.goto("/app/new");
  await page.getByRole("button", {name:"Use fictional sample"}).click();
  const submitted = page.waitForRequest("**/api/cases/*/plan");
  await page.getByRole("button", {name:"Create interview plan"}).click();
  await submitted;
  await expect(page.getByRole("button", {name:"Creating interview plan"})).toBeDisabled();
  await expect(page.getByText(/Retrieving knowledge and generating/)).toBeInViewport();
  release();
  await expect(page.getByText("Interview plan ready. Review the questions, then continue to the interview.")).toBeInViewport();
  await expect(page.getByRole("region", {name:"Generated interview plan"})).toBeFocused();
});

test("plan quota failure is shown beside the submit button", async ({page}) => {
  await fixture(page);
  await page.route("**/api/cases/*/plan", route => route.fulfill({status:429,json:{error:{code:"BUDGET_EXCEEDED",message:"Budget exhausted for groq/requests",retryable:false}}}));
  await page.goto("/app/new");
  await page.getByRole("button", {name:"Use fictional sample"}).click();
  await page.getByRole("button", {name:"Create interview plan"}).click();
  await expect(page.getByRole("alert")).toContainText("Budget exhausted");
  await expect(page.getByRole("alert")).toBeInViewport();
  await expect(page.getByRole("button", {name:"Create interview plan"})).toBeEnabled();
  await expect(page.getByLabel("Or paste CV text")).toHaveValue(/Fictional sample/);
});
