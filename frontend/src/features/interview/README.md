# Interview feature — Gana

`InterviewPage` exports a self-contained component with `sessionId` and `candidateToken` props. It owns its ElevenLabs ConversationProvider and supports consent, typed answers, supervised browser voice, timer, stop/withdrawal and confirmed completion states. Mount at `/interview/:sessionId`; capture the fragment token before clearing the URL. No global routing dependency. See `docs/gana-handoff.md` for the API and manual provider setup.
