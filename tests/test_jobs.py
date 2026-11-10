import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("jobs", ROOT / "addon/runpod_render/jobs.py")
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


def job(state="state", owner="project"):
    return dict(project_id=owner, spec=dict(state=state, start=1, end=11, step=1),
                status=dict(stage="rendering", files={"1": {"id": "uploaded"}}, updated=1))


class JobTests(unittest.TestCase):
    def test_same_basename_in_different_directories_is_not_same_project(self):
        self.assertNotEqual(jobs.project_id("a/scene.blend"), jobs.project_id("b/scene.blend"))
        self.assertEqual(jobs.project_id("a/scene.blend"), jobs.project_id("a/./scene.blend"))

    def test_legacy_and_other_files_are_not_displayed(self):
        legacy = job()
        del legacy["project_id"]
        self.assertEqual(jobs.for_project([job(), legacy, job(owner="other")], "project"), [job()])
        self.assertEqual(jobs.for_project([job()], ""), [])

    def test_progress_counts_only_requested_uploaded_frames(self):
        current = job()
        current["status"]["files"]["99"] = {}
        self.assertEqual(jobs.progress(current), (1, 11))
        current["spec"].update(start=1, end=1)
        self.assertEqual(jobs.progress(current), (1, 1))

    def test_provider_cancel_wins_over_rendering_status(self):
        current = job()
        current["cancel_requested"] = True
        jobs.reconcile(current, current["status"], {"status": "CANCELLED"})
        self.assertEqual(current["status"]["stage"], "cancelled")
        self.assertEqual(jobs.progress(current), (1, 11))
        self.assertNotIn("cancel_requested", current)

    def test_provider_completion_does_not_invent_uploaded_results(self):
        current = job()
        jobs.reconcile(current, current["status"], {"status": "COMPLETED"})
        self.assertNotEqual(current["status"]["stage"], "completed")

    def test_concurrent_inserts_and_updates_preserve_all_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            jobs.add_job(path, job())
            workers = [threading.Thread(target=jobs.add_job, args=(path, job(str(i)))) for i in range(20)]
            workers.append(threading.Thread(target=jobs.update_job,
                           args=(path, "state", lambda item: item.update(cancel_requested=True))))
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            stored = jobs.load_jobs(path)
            self.assertEqual(len(stored), 21)
            self.assertTrue(next(item for item in stored if item["spec"]["state"] == "state")["cancel_requested"])


if __name__ == "__main__":
    unittest.main()
