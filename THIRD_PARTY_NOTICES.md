# 第三方内容与翻译许可

本项目自编程序的 MIT 许可不覆盖下列第三方内容及其翻译。

教程来自 [KhronosGroup/Vulkan-Tutorial](https://github.com/KhronosGroup/Vulkan-Tutorial)。原教程由 Alexander Overvoorde 编写，Khronos Group 和其他上游贡献者持续维护。原始署名、版权及适用许可保留在上游文件、生成的逐页数据与站点许可说明中。

- 教程主体及其中文衍生内容按上游的 CC BY-SA 4.0 条件使用。
- `AI_Assisted_Vulkan`、`Advanced_Vulkan_Compute`、`Advanced_glTF`、`Building_a_Simple_Engine`、`ML_Inference`、`OpenXR_Vulkan_Spatial_Computing`、`Synchronization` 等 Holochip 扩展以各文件中的 Apache-2.0 或其他实际许可为准。
- Arm 的相关课程采用 CC BY-SA 4.0，具体以课程文件为准。
- `images/`、`attachments/` 中的图片、示例、第三方库与资源按各自文件的版权及许可使用；不能将其统一认定为 MIT 或 CC0。

`translations/google.jsonl` 包含对上述教程的机器翻译修改，适用对应原文的许可。它不是对教程内容的重新许可。生成的网站保留英文原文、原始源码链接、逐页许可，并明确标记非官方镜像及机器翻译。请以具体源文件的许可声明为准。

上游完整说明：[Introduction / Attribution](https://docs.vulkan.org/tutorial/latest/00_Introduction.html)。上游仓库许可文本备份于 `LICENSES/UPSTREAM-LICENSE.txt`。Vulkan 为 Khronos Group 的注册商标。

## 代码语法高亮

`public/syntax.js` 使用 [highlight.js 11.12.0](https://github.com/highlightjs/highlight.js)，采用 BSD-3-Clause；版权属于 Ivan Sagalaev 和上游贡献者。`public/syntax.css` 基于该项目随附的 GitHub 与 GitHub Dark 官方主题（github.com，维护者 @Hirse），保留原配色，增加本站主题选择器和代码块布局适配。Slang 高亮明确使用 C++ 语法派生并补充着色器类型和系统语义，仅用于词法配色，不进行语言识别或编译检查。

完整 highlight.js 许可见 `LICENSES/HIGHLIGHT-JS-LICENSE.txt`，也随站点发布为 `public/syntax.LICENSE.txt`。浏览器资源全部随站点托管，不从 CDN 加载。

构建使用 [esbuild 0.28.2](https://github.com/evanw/esbuild)，采用 MIT，版权属于 Evan Wallace；完整许可见 `LICENSES/ESBUILD-LICENSE.txt`。esbuild 只参与本地/CI 构建，不作为浏览器运行依赖。
