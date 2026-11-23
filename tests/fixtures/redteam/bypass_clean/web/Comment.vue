<template>
  <div class="comment">{{ body }}</div>
</template>
<script>
export default {
  props: ["body"],
  mounted() {
    this.$el.textContent = this.body;
  },
};
</script>
