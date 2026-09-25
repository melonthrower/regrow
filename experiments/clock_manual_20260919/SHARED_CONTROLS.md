# 临时框架：共享控件与本地观察

## 两种关系
- 同一控件的不同观察：仍是一个Region内的control，observations追加外观/状态，保留真实动作。已有previous_name身份机制负责对应，本次不新增Hide/Show自动判定。
- 不同Region的共享行为：保留各自control，通过shared_control_ref引用一份共同结果。五项与八项菜单不因此合并，任务完成状态不传播。

## 物理存储
沿用每区块一个region.json，不增加分散的小文件。关系首成员区块的shared_controls字典保存规范记录，其他区块控件只保存引用：

```json
{
  "shared_controls": {
    "Screen saver": {
      "scope": "behavior_only",
      "reason": "关系确认依据",
      "evidence": [{"region": "r0003", "attempt": "a0005"}],
      "members": [{"region": "r0003", "control": "c0008"}, {"region": "r0023", "control": "c0095"}],
      "results": [],
      "status": "confirmed"
    }
  }
}
```

每个成员控件增加`shared_control_ref: {region: r0003, name: Screen saver}`。这里的results由真实动作结果生成；原动作仍作为来源证据保留。固定首成员只是存放位置，不意味着其他成员属于它的子区块。

## 登记和更新
`shared_controls.link(records, name, members, reason, evidence)`显式建立关系；至少跨两个Region、引用已执行且无异常的成员动作，不能仅凭同名自动创建。reason表达本次确认范围，由调用方核实语义，校验本身不证明两个入口等价。
`discovery_step.publish`与`register_update.commit_update`发布前调用refresh。修改任一成员已登记动作结果后，规范结果随快照更新，所有成员的view/disclose读同一份知识。图像、状态、真实action、任务及跳转边不复制给其他成员。
不同目的地、异常或成员缺失时，关系标needs_review，保留冲突结果供核对，不静默覆盖。未知目的地不是不同目的地；未知证据也不产生已确认跳转。该冲突检测不是通用语义等价证明。

## 披露
任务清点的已验证入口及动作探索树提供显式共享关系、相关结果与限制；不把共享来源动作伪装成本地执行，不自动将本地任务标done。原同名候选历史仍只是候选，不等同于已确认共享关系。

## 当前验证与边界
Clock两个菜单的Screen saver已用a0005/a0067同一目的区块的实际证据显式关联，保存为新知识快照；登记来源为本次监督核对，不是Luna。旧快照、a0165待更新停点保留。
57项聚焦离线测试；本次无模型调用、无GUI动作。模型服务仍受阻，尚未验证Luna依据新共享上下文作出选择。
尚不支持Luna自动提出/批准共享关系，也不自动解决Hide/Show身份或传播相反操作的完成状态。当前可通过上述框架接口登记与读取，不以同名硬合并。
