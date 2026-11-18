# 安装（Windows）

**前置**：Windows 10/11、Python 3.10+（安装时勾 Add python.exe to PATH）、ffmpeg（`winget install Gyan.FFmpeg`）。

## 一条命令装好

```powershell
git clone https://github.com/chddydwd/dsh-eye.git
cd dsh-eye
powershell -ExecutionPolicy Bypass -File install.ps1
```

没有 git 就点 GitHub 的 **Code → Download ZIP**，解压后进文件夹「在终端中打开」，再跑上面第二行。

脚本会：把插件和 python 部分复制到 `%USERPROFILE%\.dsh\plugins\dsh-eye`、装 numpy + pillow、写 `~\.dsh\eye.json`、把插件挂进 DSH profile（带侧边栏入口）、检查 ffmpeg。**装完重启一次 DSH**，左侧栏出现「眼睛」，点「打开」。

## 可选参数

| 参数 | 作用 |
| --- | --- |
| `-Profile desktop` | 只装到某个 profile（默认全部） |
| `-Python C:\path\python.exe` | 指定 Python |
| `-SkipDeps` | 跳过 pip（依赖已装） |

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

默认保留 `eye.json` 和采集脚本；加 `-KeepFiles` 连脚本目录一起留，加 `-RemoveConfig` 连配置一起删。

## 手动装（不跑脚本）

1. 把仓库复制到 `%USERPROFILE%\.dsh\plugins\dsh-eye`（需要 lib/、python/、package.json、cordis.patch.yml）
2. `python -m pip install -r python/requirements.txt`
3. 写 `%USERPROFILE%\.dsh\eye.json`：
```json
{ "paths": { "dir": "C:/Users/<you>/.dsh/plugins/dsh-eye/python", "python": "C:/Python312/python.exe" } }
```
4. 编辑 `%USERPROFILE%\.dsh\profiles\desktop\package.json`：`dependencies` 加 `"dsh-eye": "link:C:/Users/<you>/.dsh/plugins/dsh-eye"`，`dsh.profile.bundles` 加 `"dsh-eye"`
5. `node_modules\dsh-eye` 建 junction 指向插件目录
6. 重启 DSH

## 验证

左侧栏「眼睛」面板显示帧数 / fps 即成功；或浏览器打开 http://127.0.0.1:13201/state
