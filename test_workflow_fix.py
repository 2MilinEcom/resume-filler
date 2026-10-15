import ast
from pathlib import Path
from src.verified_paid_guard import classify_paid
from src.remote_only_guard import classify_remote
base = Path(__file__).parent
source=(base/'main.py').read_text()
section=source.split('def collect_review_items(',1)[1].split('def ',1)[0]
assert 'if status not in allowed_review_statuses:' in section
assert '_collect_context_page_items(context)' not in section
assert 'REVIEW_OPEN_ALL_WORKED = env_flag("REVIEW_OPEN_ALL_WORKED", False)' in source
assert not classify_paid('Ideal candidate for this unpaid internship could grow into a paid role.').allowed
assert not classify_paid('While this internship is unpaid, academic credit is available.').allowed
assert not classify_paid('Remote internship. Academic credit may be provided.').allowed
assert classify_paid('Compensation: $20/hr for this internship.').allowed
assert not classify_remote('Marketing Intern', 'Hybrid: 3 office days every week').allowed
assert classify_remote('Remote Marketing Internship','Work from home; remote position in California.').allowed
assert '_SEEN_HANDSHAKE_JOBS.add(key)' in (base/'src/paid_remote_guard.py').read_text()
assert "company.strip().lower() == 'unknown company'" in (base/'src/paid_remote_guard.py').read_text()
print('PASS: 11 local checks; no live site visited')
