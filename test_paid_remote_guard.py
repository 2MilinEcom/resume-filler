from src.verified_paid_guard import classify_paid, verify_paid, PaidDecision
from src.remote_only_guard import classify_remote
from unittest.mock import patch

assert classify_paid('Social Media Intern. Compensation: $22/hour').allowed
assert classify_paid('Marketing internship paid $25/hr').allowed
assert classify_paid('Marketing internship is unpaid').allowed is False
assert classify_paid('Unpaid, possible discretionary bonus').allowed is False
assert classify_paid('Compensation not specified').allowed is False
assert classify_remote('Marketing Intern','Remote - California only. Work from home.').allowed
assert not classify_remote('Marketing Intern','Remote, hybrid role: 2 office days required.').allowed
assert not classify_remote('Marketing Intern','Remote with mandatory travel to office.').allowed
with patch('src.verified_paid_guard.research_compensation', return_value=PaidDecision(False,'not found')):
    assert not verify_paid('Marketing Intern','Example','remote, no salary published').allowed
print('9 static eligibility checks passed')
