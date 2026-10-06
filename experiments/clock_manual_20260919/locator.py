"""Current-frame discovery and selected-control localization using existing modules."""
import discovery_step
import step_repair


class Locator:
    def __init__(self, root, run, frame, call, repair):
        self.root, self.run, self.frame = root, run, frame
        self.call, self.repair = call, repair

    def discover(self):
        state = discovery_step.load(self.run)[2]
        batch = state.get('discovery_completion') or {}
        if batch.get('pending') and batch.get('sha256') != step_repair.helper('discovery_completion').fingerprint(self.frame):
            discovery_step.await_discovery(self.run, str(self.frame), 'fresh-discovery-'+self.frame.parent.name)
        return discovery_step.run_stage(self.root, self.run, self.call, repair=self.repair)

    def locate_control(self, request):
        return discovery_step.locate_task_control(self.run, request, self.frame)
