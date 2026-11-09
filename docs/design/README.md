# Full-page UI refresh

The shared `frontend/src/theme.css`, imported once by `main.tsx`, extends the existing forest/teal identity with slate and sage surfaces. The application root owns the full-height gradient and subtle line texture. Decoration is CSS background paint, so it creates no overlay or interactive layer.

## Updated surfaces
- Full-width landing workflow, feature, evidence, CTA and footer sections; no unstyled white section canvas.
- Navigation, workspace sidebar/header, onboarding, cards, upload forms, inputs, progress steps, notices and code/usage panels.
- Interview consent/status panels, phone permission and call controls, transcript cards, expanded evidence and reports.
- Candidate interview removes the conflicting `bg-white` utility; forms retain bounded white input surfaces.
- Responsive layouts, keyboard focus, reduced-motion and print treatment.

## Verification
- Frontend: 6 unit tests passed; production build passed.
- Playwright/Chrome: 5 visual/interaction tests passed at 1440, 820 and 390 pixels.
- Inspected full-page desktop/mobile landing screenshots from navigation to footer, mobile forms, long transcripts, expanded report, onboarding, phone controls and browser voice consent.
- Assertions check horizontal overflow, painted lower sections, focus visibility, reduced motion, navigation, expandable evidence and disabled/enabled answer/call controls.
- 19 full-page captures are under `screenshots/`. Landing captures use the actual page. Private-screen captures use explicitly labelled fictional API fixtures in tests only; no fixture data was added to the application.

## Screenshots
- [Desktop landing](screenshots/landing-1440.png)
- [Tablet landing](screenshots/landing-820.png)
- [Mobile landing](screenshots/landing-390.png)
- [Mobile upload form](screenshots/form-390.png)
- [Desktop expanded report](screenshots/expanded-report-1440.png)
- [Mobile expanded report](screenshots/expanded-report-390.png)
- [Mobile long interview](screenshots/interview-390.png)
- [Mobile phone controls](screenshots/phone-390.png)
- [Browser voice consent](screenshots/voice-consent-1440.png)

## Limits
No real call, microphone connection, model request or live candidate-data mutation was performed. Live provider behavior was not retested for this CSS-focused change. Verification used desktop Chrome with responsive emulation, not physical mobile devices or Safari/Firefox. Existing large-JavaScript-chunk build warning remains. Unrelated working-tree edits were preserved.

Commands: `npm test`, `npm run build`, `npm run test:e2e -- tests/visual-design.spec.ts` from `frontend/`.
