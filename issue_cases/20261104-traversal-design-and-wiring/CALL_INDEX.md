# 所选调用的类型与原件入口

这里列出实际request.stage；补定位、纠错不是额外GUI执行。完整截图序号见各调用INPUTS.json。

|应用|调用|实际类型|完整请求|原答|
|---|---|---|---|---|
|gimp|0283|`action_selection`|[request](evidence/gimp/calls/0283/request.json)|[response](evidence/gimp/calls/0283/response.json)|
|gimp|0284|`observation_update`|[request](evidence/gimp/calls/0284/request.json)|[response](evidence/gimp/calls/0284/response.json)|
|gimp|0336|`action_selection`|[request](evidence/gimp/calls/0336/request.json)|[response](evidence/gimp/calls/0336/response.json)|
|gimp|0337|`observation_update`|[request](evidence/gimp/calls/0337/request.json)|[response](evidence/gimp/calls/0337/response.json)|
|gimp|0338|`step_correction`|[request](evidence/gimp/calls/0338/request.json)|[response](evidence/gimp/calls/0338/response.json)|
|gimp|0339|`step_correction`|[request](evidence/gimp/calls/0339/request.json)|[response](evidence/gimp/calls/0339/response.json)|
|gimp|0340|`discovery`|[request](evidence/gimp/calls/0340/request.json)|[response](evidence/gimp/calls/0340/response.json)|
|vlc|0205|`action_selection`|[request](evidence/vlc/calls/0205/request.json)|[response](evidence/vlc/calls/0205/response.json)|
|vlc|0206|`action_target_review`|[request](evidence/vlc/calls/0206/request.json)|[response](evidence/vlc/calls/0206/response.json)|
|vlc|0207|`observation_update`|[request](evidence/vlc/calls/0207/request.json)|[response](evidence/vlc/calls/0207/response.json)|
|vlc|0251|`action_selection`|[request](evidence/vlc/calls/0251/request.json)|[response](evidence/vlc/calls/0251/response.json)|
|vlc|0252|`observation_update`|[request](evidence/vlc/calls/0252/request.json)|[response](evidence/vlc/calls/0252/response.json)|
|vlc|0253|`action_selection`|[request](evidence/vlc/calls/0253/request.json)|[response](evidence/vlc/calls/0253/response.json)|
|vlc|0254|`step_correction`|[request](evidence/vlc/calls/0254/request.json)|[response](evidence/vlc/calls/0254/response.json)|
|vlc|0255|`step_correction`|[request](evidence/vlc/calls/0255/request.json)|[response](evidence/vlc/calls/0255/response.json)|
|libreoffice-writer|0171|`action_selection`|[request](evidence/libreoffice-writer/calls/0171/request.json)|[response](evidence/libreoffice-writer/calls/0171/response.json)|
|libreoffice-writer|0172|`action_selection`|[request](evidence/libreoffice-writer/calls/0172/request.json)|[response](evidence/libreoffice-writer/calls/0172/response.json)|
|libreoffice-writer|0173|`observation_update`|[request](evidence/libreoffice-writer/calls/0173/request.json)|[response](evidence/libreoffice-writer/calls/0173/response.json)|
|libreoffice-writer|0180|`observation_update`|[request](evidence/libreoffice-writer/calls/0180/request.json)|[response](evidence/libreoffice-writer/calls/0180/response.json)|
|libreoffice-writer|0181|`observation_update`|[request](evidence/libreoffice-writer/calls/0181/request.json)|[response](evidence/libreoffice-writer/calls/0181/response.json)|
|libreoffice-writer|0182|`object_registration`|[request](evidence/libreoffice-writer/calls/0182/request.json)|本次无回复|
|libreoffice-writer|0183|`object_registration`|[request](evidence/libreoffice-writer/calls/0183/request.json)|[response](evidence/libreoffice-writer/calls/0183/response.json)|
|vs-code|0156|`task_proposal`|[request](evidence/vs-code/calls/0156/request.json)|[response](evidence/vs-code/calls/0156/response.json)|
|vs-code|0164|`observation_update`|[request](evidence/vs-code/calls/0164/request.json)|[response](evidence/vs-code/calls/0164/response.json)|
|vs-code|0165|`task_proposal`|[request](evidence/vs-code/calls/0165/request.json)|[response](evidence/vs-code/calls/0165/response.json)|
|vs-code|0169|`observation_update`|[request](evidence/vs-code/calls/0169/request.json)|[response](evidence/vs-code/calls/0169/response.json)|
|vs-code|0194|`action_target_review`|[request](evidence/vs-code/calls/0194/request.json)|[response](evidence/vs-code/calls/0194/response.json)|
|vs-code|0196|`observation_update`|[request](evidence/vs-code/calls/0196/request.json)|[response](evidence/vs-code/calls/0196/response.json)|
|vs-code|0198|`step_correction`|[request](evidence/vs-code/calls/0198/request.json)|[response](evidence/vs-code/calls/0198/response.json)|

## 关键分支顺序

- C1：`action_selection 0336 → GUI a0126 → observation_update 0337 → step_correction 0338/0339 → 登记暂挂 → discovery 0340`。
- C2：`action_selection 0253 → 投递前attempt_guard拒绝 → step_correction 0254/0255 → none`；0253没有投递。
- C3：`action_selection 0205 → action_target_review 0206 → GUI a0065 → observation_update 0207 → 发布知识`。
- C4：`action_selection 0283 → GUI a0112 → observation_update 0284 → done`。
- C5：`task_proposal 0156 → 目录代表操作 → observation_update 0164 → task_proposal 0165 → 再次目录操作 → observation_update 0169`。
- C6：`action_selection 0171/0172（同一动作格式重答）→ GUI a0041 → observation_update 0173`。
- 正常对照：`action_target_review 0194 → GUI a0040 → observation_update 0196 → step_correction 0198`。

这些顺序连接已有记录，不表示本次新执行；没有在选择、辨认或纠错时虚构GUI动作。
