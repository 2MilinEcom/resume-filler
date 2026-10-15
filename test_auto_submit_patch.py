"""Offline-only smoke tests. No browser, external network or submissions."""
import os
from pathlib import Path
import ast
from src import paid_remote_guard as guard
from src.verified_paid_guard import classify_paid
from src.remote_only_guard import classify_remote

assert not classify_paid('This is an unpaid internship.').allowed
assert not classify_paid('Academic credit only.').allowed
assert not classify_paid('Marketing internship; compensation unspecified.').allowed
assert classify_paid('This is a paid internship, $20/hr.').allowed
assert not classify_remote('Marketing Intern','Hybrid, remote 3 days; office two days per week.').allowed
assert classify_remote('Remote Marketing Intern','Fully remote, work from home anywhere in California.').allowed

class FakeLocator:
    def __init__(self,text): self.text=text
    def inner_text(self,timeout=None): return self.text
class FakePage:
    def __init__(self,text):self.text=text
    def locator(self,_):return FakeLocator(self.text)
page=FakePage('Fully remote role, no attendance required.')
os.environ['AUTO_SUBMIT_VERIFIED']='true'
os.environ['NO_AUTO_SUBMIT']='false'
os.environ['HANDSHAKE_DRAFT_ONLY']='false'
assert not guard._may_submit(page), 'unverified page cannot submit'
guard._ELIGIBLE_PAGE_IDS.add(id(page))
assert guard._may_submit(page), 'verified page ought to submit'
page.text='Must work in Palo Alto office two days per week.'
assert not guard._may_submit(page), 'onsite form must block submit'
page.text='Fully remote. Work from home.'
os.environ['NO_AUTO_SUBMIT']='true'
assert not guard._may_submit(page), 'emergency stop must block submit'
guard._ELIGIBLE_PAGE_IDS.clear()

# Ensure full project strings no longer count opened/filled applications as submitted.
main=Path(__file__).with_name('main.py').read_text()
assert 'total = handshake_submitted_count + results.get("submitted", 0)' in main
assert 'results.get("filled", 0)' not in main[main.index('def completed_count('):main.index('def process_application(')]
for name in ['main.py','src/paid_remote_guard.py','src/handshake.py','src/application_agent.py']:
    ast.parse((Path(__file__).parent/name).read_text())
print('PASS: 13 offline eligibility, gating, and syntax checks')
