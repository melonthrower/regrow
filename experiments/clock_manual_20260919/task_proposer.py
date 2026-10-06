"""Task context/schema and original proposal validation/registration as one component."""
from region_tasks import plan_request
import traversal_scope


class TaskProposer:
    @staticmethod
    def request(root, records, state, region, *, scope_review=False):
        return (traversal_scope.review_request(root, records, state, region) if scope_review
                else plan_request(root, records, state, region))

    @staticmethod
    def run(repair, request):
        # Runner owns the unchanged schema, corrections, commit_plan and publication.
        return repair.perform('task_proposal', request)
