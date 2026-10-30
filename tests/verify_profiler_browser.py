#!/usr/bin/env python3
"""Optional real Chromium acceptance; playwright is a test-only dependency."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(analysis, output):
    from playwright.sync_api import sync_playwright
    analysis,output=analysis.resolve(),output.resolve()
    assert not output.exists(),'Preserve browser attempts'
    output.mkdir(parents=True)
    data=json.loads((analysis/'analysis.json').read_text());checks=[];errors=[];requests=[]
    with sync_playwright() as api:
        browser=api.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:requests.append(request.url))
        page.goto((analysis/'index.html').as_uri());page.wait_for_selector('#hotspot-table')
        assert page.locator('#title').inner_text()==data['label']
        assert page.locator('#nav button').count()==7
        for name in ['hardware','ranges','timeline','memory','source','comparison','overview']:
            page.locator('#tab-'+name).click();assert 'active' in page.locator('#'+name).get_attribute('class')
        checks.append('Offline file report renders without a server and every navigation tab works')
        page.locator('#tab-memory').click()
        cells=page.locator('#ame-metrics').inner_text()
        returned=((data.get('memory') or {}).get('metrics') or {}).get('read_payload_bytes')
        assert str(returned) in cells if returned is not None else 'unavailable' in cells
        assert 'DRAM' in page.locator('#memory').inner_text()
        checks.append('Memory tables/cards show recorded values and explicitly retain unavailable/DRAM boundaries')
        page.screenshot(path=str(output/'memory.png'),full_page=True)
        page.locator('#tab-source').click()
        if data.get('source_pcs'):
            first=data['source_pcs'][0]
            page.locator('#source-search').fill(first['pc'])
            assert page.locator('#source table tbody tr').count()>=1
            page.locator('#source table tbody tr').first.click()
            assert first['pc'] in page.locator('#source-detail').inner_text()
        page.locator('#source-search').fill('not-a-recorded-function-08')
        assert page.locator('#source table tbody tr').count()==0
        page.locator('#source-search').fill('')
        checks.append('Source search, empty matches and recorded row detail work')
        page.locator('#tab-timeline').click()
        raw_async=[e for e in data.get('timeline',{}).get('events',[]) if e['kind']=='ame_memory']
        if raw_async:
            shown=page.locator('[data-kind="ame_memory"]')
            assert shown.count()>0,'Instruction display cap must not erase asynchronous AME returns'
            shown.first.click(force=True)
            assert 'active' in page.locator('#memory').get_attribute('class')
            assert 'PC ownership unavailable' in page.locator('#memory').inner_text()
            checks.append('Real asynchronous AME intervals survive display caps and open memory without fabricated PC ownership')
        else:
            assert page.locator('[data-kind="ame_memory"]').count()==0
            checks.append('Missing AME events produce no fabricated timeline intervals')
        page.locator('#tab-timeline').click()
        page.locator('#timeline-filter').fill('not-a-recorded-event-08')
        assert page.locator('#timeline-graph rect').count()==0
        page.locator('#timeline button').filter(has_text='Reset range').click()
        if data.get('ranges',{}).get('events'):
            page.locator('#tab-ranges').click();page.locator('#ranges button').first.click()
            assert 'active' in page.locator('#timeline').get_attribute('class')
        checks.append('Timeline filtering, reset and recorded range navigation work')
        page.locator('#tab-comparison').click()
        if data.get('comparison'):
            assert page.locator('#comparison-table tbody tr').count()==len(data['comparison']['sections']['performance']['measurements'])
        else:
            assert 'No baseline supplied' in page.locator('#comparison').inner_text()
        page.locator('#tab-overview').click()
        if data.get('overview',{}).get('hypotheses'):
            assert 'Falsifier' in page.locator('#overview').inner_text()
            assert page.locator('.hypothesis').count()==len(data['overview']['hypotheses'])
        if data.get('validation',{}).get('diagnostics_bound_to_perf') is False:
            assert 'Observation-only replay' in page.locator('#warnings').inner_text()
        checks.append('Comparison, untested experiments/falsifiers and independent performance-observer warnings are visible')
        page.screenshot(path=str(output/'overview.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        for name in ['overview','hardware','ranges','timeline','memory','source','comparison']:
            page.locator('#tab-'+name).click()
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),name
        page.locator('#tab-overview').click()
        page.screenshot(path=str(output/'mobile.png'),full_page=True)
        assert not errors,errors
        assert not [url for url in requests if url.startswith(('http:','https:'))],requests
        checks.append('Mobile layout fits; no browser JavaScript errors or external network dependencies')
        version=browser.version;browser.close()
    receipt={'schema':'xsai-prof.browser/v1','status':'passed','checks_passed':len(checks),'checks':checks,
        'analysis':str(analysis),'analysis_sha256':digest(analysis/'analysis.json'),'html_sha256':digest(analysis/'index.html'),
        'browser':'Chromium '+version,'javascript_errors':errors,'external_network_requests':[],
        'screenshots':{p.name:digest(p) for p in output.glob('*.png')}}
    (output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analysis',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();verify(args.analysis,args.output)
