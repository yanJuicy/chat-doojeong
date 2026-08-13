# React frontend structure

These rules apply to all files under `frontend/`.

- Keep `src/App.jsx` as the composition root. It may connect feature hooks and top-level panels, but it must not contain feature implementation details or inline component declarations.
- Put reusable or independently meaningful UI in `src/components/<feature>/`:
  - `chat/` for question, answer, and streaming UI.
  - `documents/` for upload, labels, document state, and document management UI.
  - `sources/` for answer evidence and source document UI.
  - `layout/` for navigation, headers, and application-wide layout.
  - `conversations/` for saved conversation lists, selection, titles, and history controls.
- Put stateful feature logic and effects in `src/hooks/`. Prefer one hook per feature, such as `useChat` or `useDocuments`.
- Put shared fixed values in `src/constants/` and stateless transformation or formatting functions in `src/utils/`.
- Keep HTTP/SSE calls in `src/api.js`; UI components must not call `fetch` directly.
- Do not create a separate file for a trivial element used only once. Extract when a block has its own responsibility, state, reuse value, or meaningful test boundary.
- When adding a feature, extend the existing feature folder first. Create a new feature folder only when the responsibility does not belong to chat, documents, sources, or layout.
- Run `pnpm build` after structural changes and keep `dist/` synchronized because FastAPI serves `frontend/dist/index.html`.
