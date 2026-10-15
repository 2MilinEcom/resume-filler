PROFILE LOCKED ANSWERS 2027 FIX

This package updates the profile and answer-bank logic with Sample's confirmed answers from 2026-10-01.
It prevents stale saved answers from overriding high-risk profile facts, especially sponsorship, graduation, GPA, test scores, and demographics.

Install:
  unzip -o ~/Downloads/profile_locked_answers_2027_fix.zip -d .
  python -m py_compile src/profile.py src/answer_bank.py src/recovery_agent.py clean_stale_answer_bank.py
  python clean_stale_answer_bank.py

Confirmed source-of-truth:
  Authorized to work in the US: Yes
  US citizen: Yes
  Sponsorship now/future: No / No
  School: UC Berkeley
  Degree: Bachelor's / B.S.
  Major: Electrical Engineering and Computer Sciences; fallback Computer Science
  Expected graduation: June 2027
  Graduation range: May 2027 - June 2027; fallback January 2027 - July 2027 when needed
  High school graduation: 2023
  GPA: 3.67; dropdown range 3.61 - 3.7
  ACT: 29
  SAT: no SAT score
  Pronouns: He/Him
  Gender: Male
  Hispanic/Latino: Yes
  Race/ethnicity: Hispanic or Latino; fallback White only if no Hispanic/Latino option exists
  Veteran: Not a veteran
  Disability: No
  Sexual orientation: Straight
  Transgender: No if required, otherwise leave blank when possible
  Prior applications: No for any company in the last 2 years
  Prior employment at company: No
  Current offers: No
  Further education immediately after undergrad: No
  Privacy statements / interview codes of conduct: Agree
  Cover letters: upload configured COVER LETTER.pdf when requested

Notes:
  This does not bypass CAPTCHA, legal attestations, or final external ATS review.
  External ATS final submission still follows your existing policy settings.
