<script lang="ts" setup>
import { ref } from 'vue'
import { useTokenStore } from '@/store'

definePage({
  style: {
    navigationBarTitleText: '登录',
  },
})

const tokenStore = useTokenStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)
let redirect = '/pages/index/index'

onLoad((query?: Record<string, string>) => {
  if (query?.redirect) {
    redirect = decodeURIComponent(query.redirect)
  }
})

async function handleLogin() {
  if (!username.value.trim() || !password.value) {
    uni.showToast({ title: '请输入账号和密码', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    await tokenStore.login({ username: username.value.trim(), password: password.value })
    uni.reLaunch({ url: redirect })
  }
  catch {
    // 错误 toast 由 http 层 / store 统一弹, 这里只复位按钮
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <view class="min-h-screen bg-white px-8 pt-24">
    <view class="mb-2 text-center text-2xl font-bold">
      BWS 预报价
    </view>
    <view class="mb-12 text-center text-sm text-gray-400">
      巴厘岛地接智能报价 · 同业版
    </view>

    <view class="mb-4">
      <view class="mb-1 text-sm text-gray-600">
        账号
      </view>
      <input
        v-model="username"
        class="box-border h-11 w-full border border-gray-300 rounded-lg border-solid px-3"
        placeholder="用户名"
        :disabled="submitting"
      >
    </view>

    <view class="mb-8">
      <view class="mb-1 text-sm text-gray-600">
        密码
      </view>
      <input
        v-model="password"
        class="box-border h-11 w-full border border-gray-300 rounded-lg border-solid px-3"
        password
        placeholder="密码"
        :disabled="submitting"
        @confirm="handleLogin"
      >
    </view>

    <button
      class="h-11 w-full rounded-lg bg-blue-600 text-white leading-11"
      :disabled="submitting"
      @click="handleLogin"
    >
      {{ submitting ? '登录中…' : '登 录' }}
    </button>
  </view>
</template>
