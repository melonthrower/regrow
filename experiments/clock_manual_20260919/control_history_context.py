"""Small identity evidence summaries; historical names are not role proof."""

def describe(region,cid):
    control=region['controls'][cid];observations=control.get('observations',[])
    indices=list(dict.fromkeys([0,len(observations)-1])) if observations else []
    rows=[{k:observations[i].get(k) for k in ('text','icon_description','possible_operation','evidence')} for i in indices]
    return {'name':control['name'],'历史首末观察（非当前可见性证明）':rows,
            '未展开的中间观察数':max(0,len(observations)-len(indices)),
            '关联任务':[{'name':n,'action':t.get('action'),'status':t.get('status')}
                        for n,t in region.get('tasks',{}).items() if t.get('control')==cid]}
