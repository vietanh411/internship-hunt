from types import SimpleNamespace

from hunt.apply import adapters


class FakeClient:
    def __init__(self, location):
        self.location, self.calls = location, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return SimpleNamespace(headers={"location": self.location})


def test_board_found_from_job_number_for_company_careers_pages():
    c = FakeClient("https://job-boards.greenhouse.io/embed/job_app?for=acadianassetmanagementllc&token=4720681006")
    assert adapters.greenhouse_board(c, "4720681006") == "acadianassetmanagementllc"
    assert c.calls[0][2] == {"follow_redirects": False}
    assert adapters.greenhouse_board(FakeClient("https://job-boards.greenhouse.io/embed/job_board?for=&error=true"), "1") is None


def test_form_opens_greenhouse_form_itself_when_posted_on_company_site():
    job = SimpleNamespace(is_test=False, source="simplify", ats_platform="greenhouse", ats_board="acadianassetmanagementllc", ats_job_id="4720681006",
                          posting_url="https://www.acadian-asset.com/careers/open-positions?gh_jid=4720681006",
                          apply_url="https://www.acadian-asset.com/careers/open-positions?gh_jid=4720681006")
    assert adapters.form_url(job) == "https://job-boards.greenhouse.io/embed/job_app?for=acadianassetmanagementllc&token=4720681006"
    job.posting_url = job.apply_url = "https://job-boards.greenhouse.io/acme/jobs/1"
    job.ats_board, job.ats_job_id = "acme", "1"
    assert adapters.form_url(job) == "https://job-boards.greenhouse.io/acme/jobs/1"


def test_fresh_non_workday_postings_and_board_order():
    from datetime import timedelta
    from hunt.db import utcnow
    from hunt.discovery import registry
    from hunt.pipeline.stages import fresh_non_workday
    job = lambda plat, hours: SimpleNamespace(application=SimpleNamespace(platform=plat), ats_platform=plat,
                                              date_posted=utcnow() - timedelta(hours=hours), date_discovered=None, created_at=None)
    assert fresh_non_workday(job("greenhouse", 20)) and fresh_non_workday(job("ashby", 40))
    assert not fresh_non_workday(job("greenhouse", 60)) and not fresh_non_workday(job("workday", 2))
    boards = [SimpleNamespace(platform=p, origin="seed", active=True, last_polled_at=None) for p in ("workday", "ashby", "workday", "greenhouse")]

    class S:
        def scalars(self, q):
            return SimpleNamespace(all=lambda: boards)
    assert [b.platform for b in registry.boards_to_poll(S(), {"workday", "ashby", "greenhouse"}, 10)] == ["ashby", "greenhouse", "workday", "workday"]
