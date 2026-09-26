<template>
  <section class="page" data-module="vfx">
    <header class="page-head">
      <div>
        <h2>特效制作管理</h2>
        <p class="page-desc">维护特效镜头，围绕镜头编号、所属集数、特效类型、制作供应商做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记特效镜头</button>
        <button class="btn" type="button" @click="exportRows">导出特效制作清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>镜头编号</span>
        <input v-model="filters.keyword" placeholder="按镜头编号检索" />
      </label>
      <label class="filter-item">
        <span>制作供应商</span>
        <input v-model="filters.vendor" placeholder="按制作供应商检索" />
      </label>
      <label class="filter-item">
        <span>制作状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <label class="filter-item">
        <span>批量动作</span>
        <select v-model="batchActionName">
          <option v-for="action in actions" :key="action" :value="action">{{ action }}</option>
        </select>
      </label>
      <button
        class="btn primary"
        type="button"
        :disabled="!selectedIds.length || batchRunning"
        @click="runBatch(selectedIds)"
      >
        {{ batchRunning ? '批量处理中…' : '批量执行' }}
      </button>
      <span class="batch-hint">已选 {{ selectedIds.length }} 条</span>
      <button v-if="selectedIds.length" class="btn ghost" type="button" @click="clearSelection">清空选择</button>
    </div>

    <div v-if="batchItems.length" class="batch-panel">
      <header class="batch-panel-head">
        <strong>批量处理结果</strong>
        <span class="batch-counts">成功 {{ succeededCount }} 条 / 失败 {{ failedCount }} 条</span>
        <span v-if="batchReplayed" class="batch-counts">该批次已提交过，结果为重放，未重复生效</span>
        <button v-if="failedCount" class="btn" type="button" :disabled="batchRunning" @click="retryFailed">
          仅重试失败项（{{ failedCount }}）
        </button>
        <button class="btn ghost" type="button" @click="clearBatchItems">收起结果</button>
      </header>
      <ul class="batch-list">
        <li v-for="item in sortedBatchItems" :key="item.id" class="batch-item">
          <span :class="item.ok ? 'badge-ok' : 'badge-fail'">{{ item.ok ? '成功' : '失败' }}</span>
          <span class="batch-label">{{ item.label ?? `#${item.id}` }}</span>
          <span class="batch-message">{{ item.message }}</span>
          <span v-if="item.status" class="batch-status">当前状态：{{ item.status }}</span>
          <button class="link" type="button" @click="openDetail(item.id)">详情</button>
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="checkbox-cell">
            <input type="checkbox" :checked="allChecked" :disabled="!rows.length" @change="toggleAll" />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="checkbox-cell">
            <input type="checkbox" :checked="isSelected(rowId(row))" @change="toggleRow(rowId(row))" />
          </td>
          <td v-for="column in columns" :key="column">{{ cellValue(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(rowId(row))">详情</button>
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length" class="batch-hint">无可用动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无特效制作数据，可先登记特效镜头</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条特效制作记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer-card">
        <header class="drawer-head">
          <strong>特效镜头详情</strong>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="drawer-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ cellValue(detail, column) }}</dd>
          </template>
          <dt>当前状态</dt>
          <dd>{{ detail.status ?? '—' }}</dd>
        </dl>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>

type BatchItem = {
  id: number
  ok: boolean
  message: string
  label: string | null
  status: string | null
}

type BatchResult = {
  ok: boolean
  message: string
  action: string
  request_id: string
  total: number
  succeeded: number
  failed: number
  replayed: boolean
  results: BatchItem[]
}

type ActionPayload = {
  ok: boolean
  message?: string
  detail?: string
}

const ENDPOINT = '/api/vfx'
const columns = ["镜头编号", "所属集数", "特效类型", "制作供应商", "渲染帧数", "预估工时", "交付版本", "制作状态"]
const actions = ["开始制作", "提交审核", "确认完成"]
const statuses = ["待制作", "制作中", "待审核", "已完成"]
// 每个状态允许执行的动作，与后端 ALLOWED_SOURCES 保持一致
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待制作": ["开始制作"],
  "制作中": ["提交审核"],
  "待审核": ["确认完成"],
  "已完成": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref({ keyword: '', vendor: '', status: '' })
const stats = ref([
  { label: '筛选范围总数', value: 0 },
  { label: '制作中镜头', value: 0 },
  { label: '待审核镜头', value: 0 },
  { label: '已完成镜头', value: 0 },
])

const selectedIds = ref<number[]>([])
const batchActionName = ref('提交审核')
const batchRunning = ref(false)
const batchItems = ref<BatchItem[]>([])
const batchReplayed = ref(false)

const detail = ref<Row | null>(null)

const allChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => isSelected(rowId(row))))
const sortedBatchItems = computed(() => [...batchItems.value].sort((a, b) => a.id - b.id))
const succeededCount = computed(() => batchItems.value.filter((item) => item.ok).length)
const failedCount = computed(() => batchItems.value.filter((item) => !item.ok).length)

function rowId(row: Row): number {
  return Number(row.id)
}

function cellValue(row: Row, column: string): string | number {
  // 「制作状态」列展示真实流转状态，其余列展示业务字段
  const value = column === '制作状态' ? row.status : row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function rowActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function isSelected(id: number): boolean {
  return selectedIds.value.includes(id)
}

function toggleRow(id: number) {
  selectedIds.value = isSelected(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => rowId(row))
}

function clearSelection() {
  selectedIds.value = []
}

function clearBatchItems() {
  batchItems.value = []
  batchReplayed.value = false
}

function resetFilters() {
  filters.value = { keyword: '', vendor: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '特效镜头登记入口尚未接入审批流'
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) params.set('keyword', filters.value.keyword.trim())
  if (filters.value.vendor.trim()) params.set('vendor', filters.value.vendor.trim())
  if (filters.value.status) params.set('status', filters.value.status)
  return params.toString()
}

function newRequestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${rowId(row)}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as ActionPayload
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '特效制作动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? '特效制作动作已生效'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '特效制作操作失败'
  }
}

async function runBatch(ids: number[]) {
  const targets = [...new Set(ids)]
  if (!targets.length || batchRunning.value) return
  batchRunning.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/actions/batch`, {
      method: 'POST',
      body: JSON.stringify({ action: batchActionName.value, ids: targets, request_id: newRequestId() }),
    })
    const payload = (await response.json()) as BatchResult & { detail?: string }
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量提交未生效，请稍后重试')
    }
    mergeBatchItems(payload)
    // 成功项移出选中，失败项保留选中，方便直接重试失败项
    const okIds = new Set(payload.results.filter((item) => item.ok).map((item) => item.id))
    selectedIds.value = selectedIds.value.filter((id) => !okIds.has(id))
    noticeMessage.value = payload.replayed ? `${payload.message}（未重复生效）` : payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量提交失败'
  } finally {
    batchRunning.value = false
  }
}

function mergeBatchItems(result: BatchResult) {
  batchReplayed.value = result.replayed
  for (const item of result.results) {
    const index = batchItems.value.findIndex((entry) => entry.id === item.id)
    if (index >= 0) {
      batchItems.value[index] = item
    } else {
      batchItems.value.push(item)
    }
  }
}

function retryFailed() {
  const failedIds = batchItems.value.filter((item) => !item.ok).map((item) => item.id)
  void runBatch(failedIds)
}

async function openDetail(id: number) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '特效镜头详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, summary] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      fetchJson<{ total: number; statuses: Record<string, number> }>(`${ENDPOINT}/stats?${query}`),
    ])
    if (!listResponse.ok) {
      throw new Error('特效镜头列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: '筛选范围总数', value: summary.total ?? 0 },
      { label: '制作中镜头', value: summary.statuses?.['制作中'] ?? 0 },
      { label: '待审核镜头', value: summary.statuses?.['待审核'] ?? 0 },
      { label: '已完成镜头', value: summary.statuses?.['已完成'] ?? 0 },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '特效制作列表读取失败'
  }
}

onMounted(reload)
</script>
