# Confluence Storage Format 速查

> Confluence 内部存储的 XHTML 子集，混合标准 HTML + Confluence 自定义 `ac:` 命名空间元素。
> 推荐用本 skill 的 pull/push 流程，不要让 markdown 转换毁掉 macro。

## 基础结构

每个页面是一段 XHTML 片段（不是完整 HTML 文档，没有 `<html>` `<head>` `<body>`）：

```html
<p>段落文本</p>
<h2>标题</h2>
<table><tbody>
  <tr><th>列1</th><th>列2</th></tr>
  <tr><td>值1</td><td>值2</td></tr>
</tbody></table>
```

## 常用 macro（ac: 命名空间）

### 目录（TOC）

```html
<ac:structured-macro ac:name="toc" ac:schema-version="1"/>
```

### 信息框 / 提示 / 警告

```html
<ac:structured-macro ac:name="info" ac:schema-version="1">
  <ac:rich-text-body>
    <p>这是信息框内容</p>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="warning" ac:schema-version="1">
  <ac:rich-text-body><p>警告内容</p></ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="note" ac:schema-version="1">
  <ac:rich-text-body><p>注意事项</p></ac:rich-text-body>
</ac:structured-macro>
```

### 代码块（含语言、行号、折叠）

```html
<ac:structured-macro ac:name="code" ac:schema-version="1">
  <ac:parameter ac:name="language">python</ac:parameter>
  <ac:parameter ac:name="linenumbers">true</ac:parameter>
  <ac:parameter ac:name="collapse">false</ac:parameter>
  <ac:plain-text-body><![CDATA[
def hello():
    print("hello")
  ]]></ac:plain-text-body>
</ac:structured-macro>
```

### Expand（折叠/展开）

```html
<ac:structured-macro ac:name="expand" ac:schema-version="1">
  <ac:parameter ac:name="title">点击展开详细数据</ac:parameter>
  <ac:rich-text-body>
    <p>展开后的内容</p>
    <table>...</table>
  </ac:rich-text-body>
</ac:structured-macro>
```

### Status（状态徽章）

```html
<ac:structured-macro ac:name="status" ac:schema-version="1">
  <ac:parameter ac:name="colour">Green</ac:parameter>
  <ac:parameter ac:name="title">PASS</ac:parameter>
</ac:structured-macro>
```

颜色：`Grey` / `Red` / `Yellow` / `Green` / `Blue`。

### 任务列表

```html
<ac:task-list>
  <ac:task>
    <ac:task-id>1</ac:task-id>
    <ac:task-status>complete</ac:task-status>
    <ac:task-body><span>已完成项</span></ac:task-body>
  </ac:task>
  <ac:task>
    <ac:task-id>2</ac:task-id>
    <ac:task-status>incomplete</ac:task-status>
    <ac:task-body><span>未完成项</span></ac:task-body>
  </ac:task>
</ac:task-list>
```

### Jira issue 嵌入

```html
<ac:structured-macro ac:name="jira" ac:schema-version="1">
  <ac:parameter ac:name="server">System Jira</ac:parameter>
  <ac:parameter ac:name="key">PROJ-123</ac:parameter>
</ac:structured-macro>
```

### 页面链接（不要硬编码 URL）

```html
<!-- 链到同空间另一页 -->
<ac:link>
  <ri:page ri:content-title="目标页标题"/>
  <ac:plain-text-link-body><![CDATA[显示文字]]></ac:plain-text-link-body>
</ac:link>

<!-- 跨空间 -->
<ac:link>
  <ri:page ri:content-title="目标页标题" ri:space-key="OTHER"/>
  <ac:plain-text-link-body><![CDATA[显示文字]]></ac:plain-text-link-body>
</ac:link>
```

### 用户提及

```html
<ac:link>
  <ri:user ri:username="zhangsan"/>
</ac:link>
```

### 附件链接

```html
<ac:link>
  <ri:attachment ri:filename="report.pdf"/>
</ac:link>

<!-- 嵌入图片 -->
<ac:image ac:width="600">
  <ri:attachment ri:filename="chart.png"/>
</ac:image>
```

### 表格列宽

```html
<table>
  <colgroup>
    <col style="width: 100px;"/>
    <col style="width: 300px;"/>
  </colgroup>
  <tbody>
    <tr><th>窄列</th><th>宽列</th></tr>
  </tbody>
</table>
```

## 转义规则

storage XHTML 是严格 XML：

| 字符 | 必须转义为 |
|------|----------|
| `<` | `&lt;` |
| `>` | `&gt;` |
| `&` | `&amp;` |
| `"` (在属性内) | `&quot;` |
| `'` (在属性内) | `&apos;` |

代码 / 长文本用 CDATA 避开转义：
```html
<ac:plain-text-body><![CDATA[
< > & " ' 都不需要转义
]]></ac:plain-text-body>
```

## 严格自闭合

storage 是 XHTML，所有空元素必须自闭合：

```html
✅ <br/>
✅ <hr/>
✅ <img src="..."/>
✅ <ac:structured-macro ac:name="toc" ac:schema-version="1"/>

❌ <br>
❌ <hr>
❌ <img src="...">
```

## 常见踩坑

### 1. macro 必须带 `ac:schema-version`

```html
✅ <ac:structured-macro ac:name="toc" ac:schema-version="1"/>
❌ <ac:structured-macro ac:name="toc"/>
```

### 2. CDATA 节不能嵌套

代码块里不能再有 `]]>`。如果代码本身含 `]]>`，需要切成两段 CDATA：
```html
<ac:plain-text-body><![CDATA[part1 ]]]]><![CDATA[> part2]]></ac:plain-text-body>
```

### 3. 表格里嵌 macro 必须用 `<ac:rich-text-body>`

```html
✅ <td><ac:structured-macro ac:name="info" ac:schema-version="1">
       <ac:rich-text-body><p>x</p></ac:rich-text-body>
     </ac:structured-macro></td>
```

### 4. `ri:content-title` 大小写敏感

```html
✅ <ri:page ri:content-title="Track B Plan"/>     <!-- 精确匹配 -->
❌ <ri:page ri:content-title="track b plan"/>     <!-- 不匹配 -->
```

### 5. 改 storage 后表格在 Confluence UI 显示走样

通常是 `<colgroup>` / `<col>` 缺失或属性错误。removed 这两行让 Confluence 用默认列宽。

### 6. markdown 转 storage 会丢

任何 `ac:structured-macro` / `ac:expand` / `ac:layout-section` 等富元素，经 server 端 markdown 转换都会被替换成纯文本或丢弃。**必须用 storage 直传**。

## 调试

看远程实际存的是什么：

```bash
atl-confluence get-page <id> --format storage
```

输出原始 XHTML，方便对照学习。

## 完整页面示例

```html
<ac:structured-macro ac:name="toc" ac:schema-version="1"/>

<h2>1. 概述</h2>
<p>本报告分析 <ac:link><ri:page ri:content-title="基础数据"/></ac:link> 的压测结果。</p>

<ac:structured-macro ac:name="info" ac:schema-version="1">
  <ac:rich-text-body>
    <p>压测时间：2026-04-27 10:00 ~ 12:00</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>2. 关键指标</h2>
<table>
  <colgroup><col style="width: 150px;"/><col style="width: 100px;"/></colgroup>
  <tbody>
    <tr><th>指标</th><th>值</th></tr>
    <tr><td>QPS</td><td>3667</td></tr>
    <tr><td>P99 响应</td><td>600ms</td></tr>
  </tbody>
</table>

<ac:structured-macro ac:name="expand" ac:schema-version="1">
  <ac:parameter ac:name="title">详细数据（点击展开）</ac:parameter>
  <ac:rich-text-body>
    <ac:structured-macro ac:name="code" ac:schema-version="1">
      <ac:parameter ac:name="language">json</ac:parameter>
      <ac:plain-text-body><![CDATA[
{"qps_p50": 3500, "qps_p99": 4200}
      ]]></ac:plain-text-body>
    </ac:structured-macro>
  </ac:rich-text-body>
</ac:structured-macro>

<ac:structured-macro ac:name="status" ac:schema-version="1">
  <ac:parameter ac:name="colour">Green</ac:parameter>
  <ac:parameter ac:name="title">PASS</ac:parameter>
</ac:structured-macro>
```
