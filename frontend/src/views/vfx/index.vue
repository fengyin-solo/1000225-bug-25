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
      <article v-for="item in statCards" :key="item.label" class="stat-card">
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
        <input v-model="filters.supplier" placeholder="按制作供应商检索" />
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
      <span class="batch-count">已选 {{ selectedIds.length }} 条</span>
      <button
        v-for="action in actions"
        :key="action"
        class="btn"
        :class="{ primary: action === '提交审核' }"
        type="button"
        :disabled="!selectedIds.length || submitting"
        @click="runBatch(action, selectedIds)"
      >
        批量{{ action }}
      </button>
      <span v-if="submitting" class="batch-hint">批量处理中…</span>
    </div>

    <div v-if="batchResult" class="batch-result">
      <p class="batch-summary">
        {{ batchResult.message }}
        <span v-if="batchResult.deduplicated" class="batch-dedup">该批次已处理过，本次未重复生效</span>
      </p>
      <ul class="batch-items">
        <li
          v-for="item in batchResult.results"
          :key="item.id"
          :class="item.ok ? 'item-ok' : 'item-fail'"
        >
          {{ item.ok ? '✓' : '✗' }} {{ item.label }}：{{ item.message }}
        </li>
      </ul>
      <button
        v-if="failedIds.length"
        class="btn primary"
        type="button"
        :disabled="submitting"
        @click="retryFailed"
      >
        仅重试失败项（{{ failedIds.length }} 条）
      </button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allSelected" @change="toggleAll" />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleRow(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无特效制作数据，可先登记特效镜头</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条特效制作记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type BatchItem = { id: number; label: string | null; ok: boolean; message: string; status: string | null }
type BatchResult = {
  ok: boolean
  message: string
  action: string
  request_id: string
  deduplicated: boolean
  total: number
  succeeded: number
  failed: number
  duplicates_ignored: number
  results: BatchItem[]
}
type Stats = { total: number; by_status: Record<string, number>; pending: number; abnormal: number }

const ENDPOINT = '/api/vfx'
const columns = ["镜头编号", "所属集数", "特效类型", "制作供应商", "渲染帧数", "预估工时", "交付版本", "制作状态"]
const actions = ["开始制作", "提交审核", "确认完成"]
const statuses = ["待制作", "制作中", "待审核", "已完成"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stats>({ total: 0, by_status: {}, pending: 0, abnormal: 0 })
const errorMessage = ref('')
const filters = ref({ keyword: '', supplier: '', status: '' })
const selectedIds = ref<number[]>([])
const submitting = ref(false)
const batchResult = ref<BatchResult | null>(null)

const statCards = computed(() =>
  statuses.map((status) => ({ label: `${status}镜头`, value: stats.value.by_status?.[status] ?? 0 })),
)
const failedIds = computed(() => batchResult.value?.results.filter((item) => !item.ok).map((item) => item.id) ?? [])
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))))

function buildQuery(): string {
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.supplier) params.set('supplier', filters.value.supplier)
  if (filters.value.status) params.set('status', filters.value.status)
  return params.toString()
}

function newRequestId(): string {
  // 每次点击生成新的幂等键；同一次提交的重试复用同一键，由后端保证不重复生效
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function resetFilters() {
  filters.value = { keyword: '', supplier: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '特效镜头登记入口尚未接入审批流'
}

function toggleRow(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : rows.value.map((row) => Number(row.id))
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '特效制作动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '特效制作操作失败'
  }
}

async function runBatch(action: string, ids: number[]) {
  if (!ids.length || submitting.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ids, request_id: newRequestId() }),
    })
    const result = (await response.json()) as BatchResult
    batchResult.value = result
    if (!response.ok) {
      throw new Error(result.message ?? '批量处理失败')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量处理失败'
  } finally {
    submitting.value = false
  }
}

function retryFailed() {
  // 只把上一批的失败项重新提交，成功项不再重复处理
  if (!batchResult.value) return
  void runBatch(batchResult.value.action, failedIds.value)
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats?${query}`),
    ])
    if (!listResponse.ok) {
      throw new Error('特效镜头列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResponse.ok) {
      stats.value = await statsResponse.json()
    }
    selectedIds.value = []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '特效制作列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.batch-count {
  font-size: 13px;
  color: var(--muted);
}
.batch-hint {
  font-size: 12px;
  color: var(--muted);
}
.batch-result {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.batch-summary {
  margin: 0 0 8px;
  font-size: 13px;
}
.batch-dedup {
  margin-left: 8px;
  color: var(--muted);
  font-size: 12px;
}
.batch-items {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
  font-size: 13px;
}
.batch-items li {
  padding: 2px 0;
}
.item-ok {
  color: #067647;
}
.item-fail {
  color: #b42318;
}
.check-col {
  width: 32px;
  text-align: center;
}
</style>
