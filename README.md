# ios-sign-install

在 **Windows（或 macOS）用纯命令行**把自签 ipa 装到 iPhone 上的最小工具链：
`zsign` 负责签名，`pymobiledevice3` 走 Apple 标准 `installation_proxy` 装机。不需要 Mac、不需要 Xcode、不需要图形签名工具。

```bash
export P12_PASSWORD='***'          # 只放环境变量，不进命令行历史

python deploy.py --ipa in.ipa \
                 --p12 cert.p12 \
                 --profile app.mobileprovision \
                 --out out.ipa --install
```

一条命令做三件事，**任一步不过就停**：

```
签名  →  自检  →  装机
```

## 为什么不是"签完直接装"

因为签名工具填错一个字段，装上去也是白装 —— 而且看不出来。`deploy.py` 在装之前先跑一遍验证：

| 验什么 | 填错的后果 |
|---|---|
| 每个二进制的 `application-identifier` 与描述文件一致（或以它为前缀） | 扩展拿不到自己的容器 / 装机被拒 |
| `com.apple.security.application-groups` ⊆ 描述文件授权的组 | `containerURL(...)` 返回 nil，数据通道全空 |
| appex 的 bundle id 以主 App 的 bundle id 为前缀 | 扩展启动即失败 |
| **DER 权益槽**（slot 7）与 XML 权益（slot 5）一致 | iOS 15+ 优先读 DER，只改一份等于没改 |

最后一条是很多人踩过的坑：签名工具只重写了 XML 权益，DER 槽还留着旧值，装上去运行时会拿到旧权限。

## 密码怎么给

`deploy.py` 默认从环境变量 `P12_PASSWORD` 读（可用 `--password-env` 改名）。

给了密码时，它会先用 `openssl` 把 p12 拆成临时 `key.pem` / `cert.pem` 再交给 zsign ——
**这样 `ps` 和 shell 历史里都不会出现密码**。临时文件在签名结束后删除。
只有机器上没有 openssl 时，才退回 zsign 的 `-p` 参数，并明确提示。

## 装什么

```
zsign              开源 iOS 签名器（Windows 有 x64 构建）
pymobiledevice3    pip install pymobiledevice3
Apple 移动设备驱动   iTunes 桌面版自带（Microsoft Store 版不行）
```

## 文档

完整流程、判据、坑表、隐私红线都在 **[SKILL.md](SKILL.md)**。
它同时是一个可被 agent 直接加载的 skill（带 `name` / `description` frontmatter）。

## 边界

- 只做**签名和装机**。改 bundle id、改 entitlements、打补丁是另一件事，不在这里。
- 需要一张**已包含目标设备 UDID** 的描述文件（Ad Hoc / 个人 / 企业）。免费 Apple ID 那套 7 天重签不走这条路。
- 不绕过任何授权校验。

## 隐私

本仓库**不含**任何证书、私钥、密码、设备 UDID 或真实 bundle id。
`.gitignore` 已挡住 `*.p12` / `*.mobileprovision` / `*.ipa` / `*.pem`，请把你的签名材料放在仓库外。
