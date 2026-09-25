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
