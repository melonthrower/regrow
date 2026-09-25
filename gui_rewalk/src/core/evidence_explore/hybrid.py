"""Explicit known navigation followed by discovery in one budget and evidence store."""
from .route import RouteRuntime
from .runtime import EvidenceRuntime


class HybridRuntime:
    def __init__(self,*,driver,agent,route,output,goal,max_calls=16,max_actions=12,before_action=None,review_inventory=False):
        self.review_inventory=review_inventory
        self.driver=driver;self.agent=agent;self.goal=goal;self.output=output
        self.max_calls=max_calls;self.max_actions=max_actions;self.before_action=before_action
        self.active=RouteRuntime(driver=driver,agent=agent,route=route,output=output,
            max_calls=max_calls,max_actions=max_actions,before_action=before_action,record_regions=True)

    @property
    def store(self):return self.active.store

    @property
    def calls(self):return self.active.calls

    @property
    def actions(self):return self.active.actions

    def run(self):
        route_result=self.active.run();self.store.write('phases/route.json',route_result)
        started=False;result=route_result
        if route_result['status']=='route_complete':
            if self.calls>=self.max_calls:
                result=dict(route_result,status='call_limit_after_route')
            else:
                previous=self.active
                self.active=EvidenceRuntime(driver=self.driver,agent=self.agent,output=self.output,
                    goal=self.goal,max_calls=self.max_calls,max_actions=self.max_actions,
                    before_action=self.before_action,separate_receipts=True,verify_before_dispatch=True,review_inventory=self.review_inventory)
                self.active.store=previous.store
                self.active.calls=previous.calls;self.active.actions=previous.actions
                started=True;result=self.active.run();self.store.write('phases/explore.json',result)
        result=dict(result,mode='route_then_explore',exploration_started=started,
            route_completed_steps=route_result['completed_steps'],route_total_steps=route_result['total_steps'],
            model_calls=self.calls,delivered_actions=self.actions,
            scope='explicit known route then bounded exploration; no canonical identity or full-app completion claim')
        self.store.write('status.json',result)
        return result
