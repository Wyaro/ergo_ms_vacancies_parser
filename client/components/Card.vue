<template>
  <div class="vp-card p-3" :class="{ clickable: clickable }">
    <slot />
  </div>
</template>

<script setup>
defineProps({
  clickable: { type: Boolean, default: false }
})
</script>

<style lang="scss" scoped>
@import '../scss/main';

.clickable {
  cursor: pointer;
}
</style>
