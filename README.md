# Resume Filler

I built Resume Filler to reduce the repetitive work involved in preparing job applications. I worked on browser navigation, form filling, application tracking, and handling the different states an application page can be in.

I included separate adapters for application sites, review and recovery steps, paid and remote job filters, and optional outreach tools. I keep application facts in a local profile so they can be reviewed and edited in one place.

## Built with

I used Python and Playwright, with optional model and email integrations.

## Inside the project

* `main.py`: the application workflow.
* `src/`: site adapters, profile templates, and review logic.
* `externship_outreach.py`: the outreach workflow.
* `docs/history/`: earlier patch and implementation notes.

## Running it

I install `requirements.txt` in a Python environment and install the Playwright browser with `python3 -m playwright install chromium`. I fill in my own local profile before using the workflow. I review the selected mode and application details before allowing any submission.

I left resumes, applicant details, browser sessions, credentials, and application records out of this copy. Some workflow modes can submit applications, so I do not use a live account just to preview the code.

## More detail

* [Development notes and outreach documentation](docs/history/README.md)
