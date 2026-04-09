<template>
  <div class="vp-step-indicator mb-4">
    <div
      v-for="(step, index) in steps"
      :key="step.key"
      class="vp-step"
      :class="{
        active:    index === currentStep,
        completed: index < currentStep
      }"
    >
      <div class="vp-step-circle">
        <Check v-if="index < currentStep" :size="14" />
        <span v-else>{{ index + 1 }}</span>
      </div>
      <span class="vp-step-label">{{ step.label }}</span>
    </div>
  </div>
</template>

<script setup>
import { Check } from 'lucide-vue-next'
defineProps({
  steps:       { type: Array, required: true },
  currentStep: { type: Number, required: true }
})
</script>

<style lang="scss" scoped>
@import '../../scss/main';
</style>
