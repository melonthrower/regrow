"""Browser contract: focused neighbours, directional anchors and continuous navigation."""
import os
from pathlib import Path
import pytest

HTML = Path(__file__).resolve().parents[1] / 'experiments/clock_manual_20260919/region_graph.html'


def test_focus_neighbours_and_animated_navigation(tmp_path):
    from playwright.sync_api import sync_playwright
    nodes = [dict(id=i, name=i, description='', image=None, current=False, working=i=='a',
                  progress={'pending': [], 'complete': False},
                  controls=[dict(id='c',name='Open',description='',image=None,tasks=[],actions=[])])
             for i in 'abcde']
    edges = [dict(source=a,target=b,control='c',control_name='Open',operation='click',attempts=['1'],description='')
             for a,b in [('a','b'),('c','a'),('b','d')]]
    with sync_playwright() as p:
        executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
        browser = p.chromium.launch(headless=True, executable_path=executable, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.route('http://graph.test/',lambda r:r.fulfill(body=HTML.read_text(),content_type='text/html'))
        page.route('**/graph.json',lambda r:r.fulfill(json=dict(nodes=nodes,edges=edges,working='a',app='fixture',snapshot='1')))
        page.goto('http://graph.test/')
        page.wait_for_timeout(800)
        assert page.locator('.node').count()==3  # b and c are neighbours; d and e are unrelated
        assert page.locator('.edge.outgoing').count()==1
        assert page.locator('.edge.incoming').count()==1
        assert page.locator('.node.selected .control-anchor').count()==1
        def endpoint(selector, end=False):
            return page.locator(selector).evaluate("""(e,end)=>{
                const p=e.getPointAtLength(end?e.getTotalLength():0);
                const q=new DOMPoint(p.x,p.y).matrixTransform(e.getScreenCTM());
                return {x:q.x,y:q.y};
            }""",end)
        start=endpoint('.edge.outgoing')
        anchor=page.locator('.node.selected .control-anchor rect').bounding_box()
        assert abs(start['y']-(anchor['y']+anchor['height']/2))<2
        assert min(abs(start['x']-anchor['x']),abs(start['x']-anchor['x']-anchor['width']))<2
        end=endpoint('.edge.incoming',True)
        card=page.locator('.node.selected .card').bounding_box()
        assert min(abs(end['x']-card['x']),abs(end['x']-card['x']-card['width']),
                   abs(end['y']-card['y']),abs(end['y']-card['y']-card['height']))<2
        b=page.locator('.node[data-id="b"]')
        before=b.bounding_box()
        b.evaluate('(e)=>{window.savedNode=e;e.dispatchEvent(new MouseEvent("click",{bubbles:true}))}')
        page.wait_for_timeout(180)
        during=b.bounding_box()
        assert during['x'] != before['x'] or during['y'] != before['y']
        assert b.evaluate('(e)=>e===window.savedNode')
        assert page.locator('.node[data-id="c"]').count()==1  # departing node retained during motion
        page.wait_for_timeout(650)
        assert set(page.locator('.node').evaluate_all('(es)=>es.map(e=>e.dataset.id)'))=={'a','b','d'}
        assert page.locator('.node.selected').get_attribute('data-id')=='b'
        assert page.locator('.edge.incoming').count()==1
        assert page.locator('.edge.outgoing').count()==1
        page.locator('.node[data-id="d"]').evaluate('(e)=>e.click ? e.click() : e.dispatchEvent(new MouseEvent("click"))')
        page.wait_for_timeout(80)
        page.locator('#search').fill('e')
        page.locator('#search-results button').get_by_text('e',exact=True).click()
        page.wait_for_timeout(800)
        assert page.locator('.node').count()==1
        assert page.locator('.edge').count()==0
        page.screenshot(path=str(tmp_path/'isolated.png'))
        assert not errors
        browser.close()


def test_page_tree_polls_frame_status_before_snapshot_changes(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    view = {'sync_status': 'observed', 'names': {}, 'goal': {}, 'origin': {},
            'current_tree': [{'ref': 'dialog', 'name': '添加城市弹窗', 'controls': [], 'children': []}]}
    value = {'nodes': [], 'edges': [], 'app': 'test', 'snapshot': 'unchanged', 'page_context': view}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'), args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('http://graph.test/', lambda r: r.fulfill(body=HTML.read_text(), content_type='text/html'))
        page.route('**/graph.json', lambda r: r.fulfill(json=value))
        page.goto('http://graph.test/')
        expect(page.locator('#page-map')).to_contain_text('依据最近一次已登记观察')
        page.locator('#page-map details summary').first.click()
        view['sync_status'] = 'checking'
        expect(page.locator('#page-map')).to_contain_text('新画面尚未登记', timeout=5000)
        assert not page.locator('#page-map details').first.evaluate('(e)=>e.open')
        assert value['snapshot'] == 'unchanged'
        view['sync_status'] = 'localized'
        view['current_tree'][0]['controls'] = [{'name': '搜索框', 'state': '已禁用', 'evidence': 'needs_recheck'}]
        expect(page.locator('#page-map')).to_contain_text('已定位当前区块', timeout=5000)
        expect(page.locator('#page-map')).to_contain_text('搜索框')
        expect(page.locator('#page-map')).not_to_contain_text('状态待核对')
        expect(page.locator('#page-map')).not_to_contain_text('已禁用')
        view['origin'] = {'known_entries': [{'from_regions': ['World'], 'to_regions': ['dialog'],
            'via': {'attempt': 'old', 'control': 'Add'}, 'parent_branches': []}]}
        expect(page.locator('#page-map')).to_contain_text('已登记历史入口（未证明是本次来路）', timeout=5000)
        expect(page.locator('#page-map')).not_to_contain_text('直接进入来源')
        value['snapshot'] = 'after-add'
        view['sync_status'] = 'observed'
        view['current_tree'] = [{'ref': 'world', 'name': 'World 城市列表', 'controls': [], 'children': []}]
        expect(page.locator('#page-map')).to_contain_text('World 城市列表', timeout=5000)
        expect(page.locator('#page-map')).not_to_contain_text('添加城市弹窗')
        page.screenshot(path=str(tmp_path/'live-map.png'))
        assert not errors
        browser.close()


def test_map_control_history_and_unbound_effects_remain_distinct(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from tests.test_recovery_discovery import mod
    from tests.test_current_page_context import case
    records,state,_=case(tmp_path)
    records['world']['tasks']['inspect']['result_evidence']='历史任务尚有归属缺口'
    records['world']['actions']['a2']={'control':None,'operation':'click','delivery':'executed_receipt_zero','association':{'status':'unconfirmed','target':'待核对入口'},'result':{'description':'内容保留，具体来源未确认'}}
    records['world']['actions']['a3']={'control':'open','operation':'click','delivery':'not_executed','result':{'description':'未执行提案不能变成观察'}}
    view=mod('page_context').build(records,state);view['sync_status']='checking'
    value={'nodes':[],'edges':[],'app':'test','snapshot':'1','page_context':view}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'),args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('http://graph.test/',lambda r:r.fulfill(body=HTML.read_text(),content_type='text/html'))
        page.route('**/graph.json',lambda r:r.fulfill(json=value))
        page.goto('http://graph.test/')
        expect(page.locator('#page-map')).to_contain_text('登记动作顺序')
        expect(page.locator('#page-map')).to_contain_text('历史任务尚有归属缺口')
        bound=page.locator('details[data-key="history:world:open"]')
        bound.locator('summary').click()
        expect(bound).to_contain_text('Observed actual result')
        expect(bound).to_contain_text('没有已执行回执，不能作为实际结果')
        expect(bound).not_to_contain_text('未执行提案不能变成观察')
        expect(page.locator('details[data-key="history"] > summary')).not_to_contain_text('已发生')
        expect(bound).not_to_contain_text('内容保留')
        unbound=page.locator('details[data-key="history:world:unbound"]')
        unbound.locator('summary').click()
        expect(unbound).to_contain_text('内容保留，具体来源未确认')
        value['snapshot']='2';view['sync_status']='observed'
        expect(page.locator('#page-map')).to_contain_text('依据最近一次已登记观察',timeout=5000)
        assert bound.evaluate('(e)=>e.open') and unbound.evaluate('(e)=>e.open')
        page.screenshot(path=str(tmp_path/'control-history.png'))
        assert not errors
        browser.close()
