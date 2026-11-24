---
id: D-0022
decided_by: owner
decided_on: 2026-11-23
kind: scope
---

# Shape it in chat: a person can work out the spec with Rihma in conversation

The owner (2026-11-23): a user should be able to "just open a chat and maybe give a file if they want, or
just figure out the specs with Rihmasto ... the factory helps to generate the specs and specify what's
needed", not only start from a written plan or a form.

**What this means:**
- **Start with anything.** A person opens a chat, in the cockpit, on a phone, or from a website's
  need-chat handing over, and starts with nothing, a sentence, or files: text and Markdown, Word
  documents (read with the standard library) and pasted text. A PDF is read when a reader is available
  and is otherwise asked for as pasted text, never silently skipped.
- **The gaps, one at a time.** Rihma restates the need, proposes a work profile and a posture with their
  preview, and asks the gaps the input left, one at a time in the conversation, in the person's
  language. The person answers, says "you assume this", or says "I don't know yet", which records an
  open question.
- **Signed like the Inbox.** Each answer is recorded exactly as an Inbox answer would be: signed by the
  person and persona, with the chat message as its source. An assumption Rihma makes carries a due date.
  Nothing the person said is put in their mouth: a model's summary of an answer is shown for the person
  to confirm before it counts.
- **The draft is always visible.** Beside the chat, the draft spec takes shape (requirements with their
  criteria, where each came from), and the person can change it by saying so. Each change is a proposed
  edit the person confirms.
- **A person confirms the result.** When the person confirms, the project is created or updated with the
  conversation kept as its request, and continues as any other: the spec, the hashed contract, the plan,
  the build. Under a regulated posture the confirmation includes every requirement; under autopilot in a
  sandbox the person's delegation applies (D-0007).
- **The same flow on the command line.** It is also available as `rihmasto shape`, and it is tested end to
  end in a real browser, on a phone width too.
