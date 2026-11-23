<template>
  <div class="comment" v-html="body"></div> <!-- seeded: RT-JS-DOMXSS -->
</template>
<script>
export default {
  props: ["body"],
  mounted() {
    this.$el.innerHTML = this.body; // seeded: RT-JS-DOMXSS
  },
};
</script>
