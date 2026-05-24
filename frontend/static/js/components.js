/* BWS 预报价系统 · Vue 组件库 */

const API = '/api/v1';
const http = axios.create({ baseURL: API, timeout: 60000, withCredentials: true });

// ============================================================
//  报价生成器
// ============================================================
const QuoteBuilder = {
  props: [
    'destinations', 'hotels', 'attractions', 'restaurants',
    'vehicles', 'guides', 'templates', 'spas', 'waters', 'teas', 'optionals'
  ],
  emits: ['saved'],
  data() {
    return {
      form: {
        agency_name: '',
        customer_name: '',
        pax_adult: 2,
        pax_child: 0,
        pax_senior: 0,
        start_date: null,
        end_date: null,
        destination_codes: ['DPS'],
        season: 'shoulder',
        customer_type: 'family',
        is_first_time_agency: false,
        // 航班(用于推算首日/末日可用小时)
        arrival_at: null,
        departure_at: null,
        arrival_airport: 'DPS',
        departure_airport: 'DPS',
        days: []
      },
      result: null,
      loading: false,
      currentQuoteId: null,
      // 模板详情弹窗
      tplDetailDialog: false,
      tplDetail: null,
      tplDetailLoading: false,
      // 景点互斥规则
      attrConflicts: [],
    };
  },
  computed: {
    totalDays() {
      if (!this.form.start_date || !this.form.end_date) return this.form.days.length || 1;
      const ms = new Date(this.form.end_date) - new Date(this.form.start_date);
      return Math.max(Math.round(ms / 86400000) + 1, 1);
    },
    activeDestinationCode() {
      return this.form.destination_codes[0] || 'DPS';
    },
    filteredHotels() { return this.filterByDest(this.hotels); },
    filteredAttractions() { return this.filterByDest(this.attractions); },
    filteredRestaurants() { return this.filterByDest(this.restaurants); },
    filteredVehicles() { return this.filterByDest(this.vehicles); },
    filteredGuides() { return this.filterByDest(this.guides); },
    filteredTemplates() { return this.filterByDest(this.templates); },
    filteredSpas() { return this.filterByDest(this.spas); },
    filteredWaters() { return this.filterByDest(this.waters); },
    filteredTeas() { return this.filterByDest(this.teas); },
  },
  methods: {
    filterByDest(list) {
      if (!list) return [];
      const dest = this.destinations.find(d => d.code === this.activeDestinationCode);
      if (!dest) return list;
      return list.filter(x => x.destination_id === dest.id);
    },
    syncDays() {
      const target = this.totalDays;
      while (this.form.days.length < target) {
        this.form.days.push(this.makeEmptyDay(this.form.days.length + 1));
      }
      while (this.form.days.length > target) {
        this.form.days.pop();
      }
      this.form.days.forEach((d, i) => { d.day_index = i + 1; });
    },
    makeEmptyDay(index) {
      return {
        day_index: index,
        date: null,
        is_free: false,
        free_hours: 0,           // 0 全程, 4 半天自由, 8 全天自由
        day_type: 'full',        // v0.9.3: full/half/arrival/departure
        template_id: null,
        hotel_id: null, hotel_room_id: null,
        vehicle_id: null, guide_id: null,
        breakfast_included: false,
        lunch_restaurant_id: null,
        dinner_restaurant_id: null,
        afternoon_tea_id: null,
        spa_id: null, water_activity_id: null,
        notes: '',
        attractions: []
      };
    },
    // v0.9.3: day_type 改变时自动联动 (送机日去酒店 + 早餐 ON)
    onDayTypeChange(day) {
      if (day.day_type === 'departure') {
        day.hotel_id = null;
        day.hotel_room_id = null;
        day.breakfast_included = true;
      }
    },
    // v0.9.3: 复制某日全部字段, 在它后面插入一天
    copyDayAfter(idx) {
      const src = this.form.days[idx];
      const copy = JSON.parse(JSON.stringify(src));
      copy.day_index = idx + 2;
      copy.date = null;  // 日期不复制 (顺延一天意义模糊, 让用户自填)
      copy.attractions = (src.attractions || []).map((a, i) => ({
        attraction_id: a.attraction_id,
        order_index: i + 1,
        stay_minutes: a.stay_minutes,
      }));
      this.form.days.splice(idx + 1, 0, copy);
      this.form.days.forEach((d, i) => { d.day_index = i + 1; });
      ElementPlus.ElMessage.success(`已复制第 ${idx + 1} 天到第 ${idx + 2} 天`);
    },
    onFreeHoursChange(day) {
      day.is_free = day.free_hours >= 8;
    },
    async addAttraction(day, attractionId) {
      if (!attractionId) return;
      // 重复检查
      if (day.attractions.some(a => a.attraction_id === attractionId)) {
        ElementPlus.ElMessage.info('该景点已在本日');
        return;
      }
      // 互斥检查 — 与同日已选景点配对
      const existingIds = day.attractions.map(a => a.attraction_id);
      const conflicts = this.attrConflicts.filter(r => r.active &&
        ((r.attraction_a_id === attractionId && existingIds.includes(r.attraction_b_id)) ||
         (r.attraction_b_id === attractionId && existingIds.includes(r.attraction_a_id))));
      const errCfl = conflicts.find(c => c.severity === 'error');
      if (errCfl) {
        try {
          await ElementPlus.ElMessageBox.confirm(
            `[互斥规则·错误] ${errCfl.message || '该景点与已选景点不可同日'}\n\n仍要添加吗?`,
            '景点冲突', { type: 'error', confirmButtonText: '强制添加', cancelButtonText: '取消' }
          );
        } catch (e) { return; }
      } else if (conflicts.length) {
        ElementPlus.ElMessage.warning(`[互斥规则] ${conflicts[0].message || '该景点与同日景点有冲突,请确认'}`);
      }

      day.attractions.push({
        attraction_id: attractionId,
        order_index: day.attractions.length + 1,
        stay_minutes: null
      });

      // 智能模板建议:此景点属于某模板的核心 → 弹建议
      if (day.attractions.length === 1 && !day.template_id) {
        const matched = (this.templates || []).filter(t =>
          (t.attractions || []).some(a => a.attraction_id === attractionId));
        if (matched.length === 1) {
          const tpl = matched[0];
          try {
            await ElementPlus.ElMessageBox.confirm(
              `检测到此景点属于"${tpl.name_zh}",是否一键套用整个一日游(共 ${tpl.attractions?.length || 0} 个景点)?`,
              '智能模板建议',
              { confirmButtonText: '套用模板', cancelButtonText: '不用,仅保留这一个', type: 'info' }
            );
            day.template_id = tpl.id;
            this.applyTemplate(day);
          } catch (e) { /* 用户拒绝 */ }
        } else if (matched.length > 1) {
          ElementPlus.ElMessage.info(`此景点出现在 ${matched.length} 个模板中,可在上方"一日游模板"下拉选择`);
        }
      }
    },
    removeAttraction(day, idx) {
      day.attractions.splice(idx, 1);
      day.attractions.forEach((a, i) => { a.order_index = i + 1; });
    },
    moveAttraction(day, idx, dir) {
      const target = idx + dir;
      if (target < 0 || target >= day.attractions.length) return;
      const tmp = day.attractions[idx];
      day.attractions.splice(idx, 1);
      day.attractions.splice(target, 0, tmp);
      day.attractions.forEach((a, i) => { a.order_index = i + 1; });
    },
    attractionConflictTips(day, item) {
      // 返回与同日其他景点的冲突描述列表
      const otherIds = day.attractions.map(a => a.attraction_id).filter(id => id && id !== item.attraction_id);
      const tips = [];
      for (const r of this.attrConflicts) {
        if (!r.active) continue;
        let otherId = null;
        if (r.attraction_a_id === item.attraction_id && otherIds.includes(r.attraction_b_id)) otherId = r.attraction_b_id;
        else if (r.attraction_b_id === item.attraction_id && otherIds.includes(r.attraction_a_id)) otherId = r.attraction_a_id;
        if (otherId) {
          const otherName = this.attractions?.find(a => a.id === otherId)?.name_zh || `#${otherId}`;
          tips.push({ severity: r.severity, msg: r.message || '冲突', otherName });
        }
      }
      return tips;
    },
    addDay() {
      this.form.days.push(this.makeEmptyDay(this.form.days.length + 1));
    },
    removeDay(idx) {
      if (this.form.days.length <= 1) return;
      this.form.days.splice(idx, 1);
      this.form.days.forEach((d, i) => { d.day_index = i + 1; });
    },
    applyTemplate(day) {
      if (!day.template_id) return;
      const tpl = this.templates.find(t => t.id === day.template_id);
      if (!tpl) return;
      day.attractions = (tpl.attractions || []).map((a, i) => ({
        attraction_id: a.attraction_id,
        order_index: i + 1,
        stay_minutes: a.stay_minutes
      }));
      const lunch = (tpl.restaurants || []).find(r => r.meal_type === 'lunch');
      if (lunch) day.lunch_restaurant_id = lunch.restaurant_id;
      const dinner = (tpl.restaurants || []).find(r => r.meal_type === 'dinner');
      if (dinner) day.dinner_restaurant_id = dinner.restaurant_id;
      ElementPlus.ElMessage.success(`已应用模板：${tpl.name_zh}`);
    },
    hotelRoomsFor(hotelId) {
      const h = this.hotels.find(x => x.id === hotelId);
      return h ? (h.rooms || []) : [];
    },
    async saveAndCalculate() {
      this.syncDays();
      this.loading = true;
      try {
        const r1 = await http.post('/quotes', this.form);
        this.currentQuoteId = r1.data.id;
        const r2 = await http.post(`/quotes/${r1.data.id}/calculate`);
        this.result = r2.data;
        ElementPlus.ElMessage.success(`报价已生成：${r2.data.quote_no}`);
        this.$emit('saved');
      } catch (e) {
        console.error(e);
        ElementPlus.ElMessage.error('生成失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.loading = false;
      }
    },
    feasibilityClass(status) {
      return { fail: 'feasibility-error', warning: 'feasibility-warning', pass: 'feasibility-pass' }[status] || '';
    },
    async showTemplateDetail(tid) {
      if (!tid) return;
      this.tplDetailDialog = true;
      this.tplDetailLoading = true;
      try { this.tplDetail = (await http.get(`/templates/${tid}`)).data; }
      catch (e) { ElementPlus.ElMessage.error('加载模板详情失败'); }
      finally { this.tplDetailLoading = false; }
    },
    // 估算某天实际可用小时数(基于航班 + 默认 14h 全天可用)
    dayAvailableHours(dayIndex) {
      const total = this.form.days.length || 1;
      // 中间天 默认 14h 全天可用(08:00-22:00)
      let hours = 14;
      // 首日:抵达后 1h 入住缓冲
      if (dayIndex === 1 && this.form.arrival_at) {
        const t = new Date(this.form.arrival_at);
        const ah = t.getHours() + t.getMinutes() / 60;
        hours = Math.max(0, 22 - (ah + 1));
      }
      // 末日:出发前 1.5h 到机场
      if (dayIndex === total && this.form.departure_at) {
        const t = new Date(this.form.departure_at);
        const dh = t.getHours() + t.getMinutes() / 60;
        hours = Math.max(0, (dh - 1.5) - 8);
      }
      return Math.round(hours * 10) / 10;
    },
    dayAvailableTip(dayIndex) {
      const total = this.form.days.length || 1;
      const isFirst = dayIndex === 1;
      const isLast  = dayIndex === total;
      if (!isFirst && !isLast) return null;
      if (isFirst && !this.form.arrival_at) return null;
      if (isLast  && !this.form.departure_at) return null;
      const h = this.dayAvailableHours(dayIndex);
      const role = isFirst ? '抵达日' : '离开日';
      const compressed = 14 - h;
      let warn = '';
      if (h < 4)  warn = '⚠️ 时间过短,基本只够入住/送机';
      else if (h < 8) warn = '⚠️ 半天可用,自费推单空间小';
      return { hours: h, role, compressed: Math.round(compressed * 10) / 10, warn };
    },
    async loadAttrConflicts() {
      try { this.attrConflicts = (await http.get('/settings/attraction-conflicts')).data || []; }
      catch (e) { this.attrConflicts = []; }
    },
    fmtNum(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n.toLocaleString() : '—';
    },
    fmtVal(v) {
      if (v === null || v === undefined || v === '') return '—';
      const n = Number(v);
      return Number.isFinite(n) ? v : '—';
    }
  },
  watch: {
    'form.start_date'() { this.syncDays(); },
    'form.end_date'() { this.syncDays(); },
  },
  mounted() {
    this.syncDays();
    this.loadAttrConflicts();
  },
  template: `
    <div class="quote-builder">
      <div class="bws-card">
        <h3>📋 基本信息</h3>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="B 端旅行社">
              <el-input v-model="form.agency_name" placeholder="如：上海康辉" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="客户名">
              <el-input v-model="form.customer_name" placeholder="如：李先生 4 人蜜月" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6" :md="3">
            <el-form-item label="成人">
              <el-input-number v-model="form.pax_adult" :min="1" :max="50" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6" :md="3">
            <el-form-item label="儿童">
              <el-input-number v-model="form.pax_child" :min="0" :max="20" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6" :md="3">
            <el-form-item label="长者">
              <el-input-number v-model="form.pax_senior" :min="0" :max="50" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="3">
            <el-form-item label="目的地">
              <el-select v-model="form.destination_codes[0]" style="width:100%">
                <el-option v-for="d in destinations" :key="d.code" :label="d.name_zh" :value="d.code" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="3">
            <el-form-item label="季节">
              <el-select v-model="form.season" style="width:100%">
                <el-option label="淡季" value="low" />
                <el-option label="平季" value="shoulder" />
                <el-option label="旺季" value="high" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="出发日期">
              <el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="返回日期">
              <el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="客户类型">
              <el-select v-model="form.customer_type">
                <el-option label="蜜月" value="honeymoon" />
                <el-option label="亲子" value="family_kids" />
                <el-option label="年轻人" value="young" />
                <el-option label="家庭" value="family" />
                <el-option label="老年" value="senior" />
                <el-option label="MICE" value="mice" />
                <el-option label="婚礼" value="wedding" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="首次合作">
              <el-switch v-model="form.is_first_time_agency" />
            </el-form-item>
          </el-col>
        </el-row>
      </div>

      <div class="bws-card">
        <h3>✈️ 航班信息(可选,影响首日/末日可用时长)</h3>
        <el-row :gutter="12">
          <el-col :xs="24" :md="9">
            <el-form-item label="抵达时间">
              <el-date-picker v-model="form.arrival_at" type="datetime" placeholder="如:2026-08-12 18:30"
                              format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="抵达机场">
              <el-select v-model="form.arrival_airport">
                <el-option label="DPS 巴厘" value="DPS" />
                <el-option label="CGK 雅加达" value="CGK" />
                <el-option label="LOK 龙目" value="LOK" />
                <el-option label="KMD 科莫多" value="KMD" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="9">
            <el-form-item label="离开时间">
              <el-date-picker v-model="form.departure_at" type="datetime" placeholder="如:2026-08-16 09:00"
                              format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="3">
            <el-form-item label="离开机场">
              <el-select v-model="form.departure_airport">
                <el-option label="DPS 巴厘" value="DPS" />
                <el-option label="CGK 雅加达" value="CGK" />
                <el-option label="LOK 龙目" value="LOK" />
                <el-option label="KMD 科莫多" value="KMD" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <p style="color:#6b7280;font-size:12px;margin:0">
          💡 系统按"抵达 +1h 入住缓冲"和"离开 −1.5h 机场缓冲"推算可用小时,注入赌自费规则的总自由时长。
        </p>
      </div>

      <div class="bws-card">
        <h3>🗓 按天编辑（{{ form.days.length }} 天）</h3>
        <div v-for="(day, idx) in form.days" :key="idx"
             :class="['quote-day-card', { 'is-free': day.is_free }]">
          <div :class="['day-header', { 'is-free': day.free_hours >= 8 }]">
            <div>
              <strong>Day {{ day.day_index }}</strong>
              <span style="margin-left:12px;font-size:12px;opacity:0.85">
                {{ ({full:'🚌 全天',half:'🌗 半天',arrival:'🛬 抵达日',departure:'🛫 送机日'})[day.day_type || 'full'] }}
                <span v-if="(day.day_type || 'full') !== 'full'" style="margin-left:4px">· 车导 0.5 倍计费</span>
              </span>
              <span v-if="day.free_hours >= 8" style="margin-left:8px;font-size:12px;opacity:0.85">🌴 全天自由</span>
              <span v-else-if="day.free_hours === 4" style="margin-left:8px;font-size:12px;opacity:0.85">🌗 半天自由</span>
              <span v-if="dayAvailableTip(day.day_index)" style="margin-left:12px;font-size:12px;opacity:0.95;background:rgba(255,255,255,0.18);padding:2px 8px;border-radius:4px">
                ✈️ {{ dayAvailableTip(day.day_index).role }} 实际可用 ~{{ dayAvailableTip(day.day_index).hours }}h
                {{ dayAvailableTip(day.day_index).warn }}
              </span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end">
              <!-- v0.9.3: 行程时长 (4 选 1, 影响车导计费 + 离开日去酒店) -->
              <el-radio-group v-model="day.day_type" size="small"
                              @change="onDayTypeChange(day)" fill="#0ea5e9">
                <el-radio-button value="full" title="全天用车">全天</el-radio-button>
                <el-radio-button value="half" title="半天用车, 0.5 倍计费">半天</el-radio-button>
                <el-radio-button value="arrival" title="抵达日, 下午到, 车导按 0.5 天">抵达日</el-radio-button>
                <el-radio-button value="departure" title="送机日, 上午送机, 无住宿, 含早, 车导按 0.5 天">送机日</el-radio-button>
              </el-radio-group>
              <el-radio-group v-model="day.free_hours" size="small"
                              @change="onFreeHoursChange(day)" fill="#f59e0b">
                <el-radio-button :value="0">全程行程</el-radio-button>
                <el-radio-button :value="4">半天自由</el-radio-button>
                <el-radio-button :value="8">全天自由</el-radio-button>
              </el-radio-group>
              <button type="button"
                      class="btn-day-copy"
                      @click="copyDayAfter(idx)"
                      title="复制此天到下一天 (全字段克隆)"
                      style="background:#10b981;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px">📋 复制</button>
              <button type="button"
                      v-if="form.days.length > 1"
                      class="btn-day-remove"
                      @click="removeDay(idx)"
                      title="删除该天">× 删除</button>
            </div>
          </div>
          <div class="day-body">
            <!-- v0.9.3: 送机日不入住, 隐藏酒店/房型. 早餐默认 ON (前一晚含早) -->
            <div v-if="day.day_type === 'departure'"
                 style="padding:10px;background:#fef3c7;border:1px solid #fbbf24;border-radius:6px;margin-bottom:12px;font-size:13px;color:#78350f">
              🛫 <strong>送机日</strong> — 不入住酒店,早餐由前一晚酒店提供;车导按半天计费
            </div>
            <el-row v-if="day.day_type !== 'departure'" :gutter="12">
              <el-col :xs="24" :md="6">
                <el-form-item label="酒店">
                  <el-select v-model="day.hotel_id" filterable clearable placeholder="选酒店">
                    <el-option v-for="h in filteredHotels" :key="h.id" :label="h.name_zh" :value="h.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="6">
                <el-form-item label="房型">
                  <el-select v-model="day.hotel_room_id" clearable placeholder="选房型">
                    <el-option v-for="r in hotelRoomsFor(day.hotel_id)" :key="r.id"
                               :label="r.room_type" :value="r.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="12" :md="3">
                <el-form-item label="含早">
                  <el-switch v-model="day.breakfast_included" />
                </el-form-item>
              </el-col>
            </el-row>

            <template v-if="day.free_hours < 8">
              <el-row :gutter="12">
                <el-col :xs="24" :md="8">
                  <el-form-item label="一日游模板">
                    <div style="display:flex;gap:6px;width:100%">
                      <el-select v-model="day.template_id" clearable placeholder="可选: 套用模板"
                                 @change="applyTemplate(day)" style="flex:1">
                        <el-option v-for="t in filteredTemplates" :key="t.id" :label="t.name_zh" :value="t.id" />
                      </el-select>
                      <el-button v-if="day.template_id" size="small" @click="showTemplateDetail(day.template_id)" title="查看模板内容">👁</el-button>
                    </div>
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :md="8">
                  <el-form-item label="用车">
                    <el-select v-model="day.vehicle_id" clearable placeholder="选车型">
                      <el-option v-for="v in filteredVehicles" :key="v.id"
                                 :label="\`\${v.seat_count} 座 \${v.vehicle_type}\`" :value="v.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :md="8">
                  <el-form-item label="导游">
                    <el-select v-model="day.guide_id" clearable placeholder="选导游">
                      <el-option v-for="g in filteredGuides" :key="g.id"
                                 :label="\`\${g.name_zh} (\${g.language})\`" :value="g.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="今日景点路线">
                <div style="display:flex;gap:8px;margin-bottom:10px;width:100%">
                  <el-select placeholder="+ 添加景点 (输入名字搜索)" filterable
                             :model-value="null"
                             @change="(v) => addAttraction(day, v)" style="flex:1">
                    <el-option v-for="a in filteredAttractions" :key="a.id"
                               :label="\`\${a.name_zh} (\${a.area || '未分区'})\`" :value="a.id" />
                  </el-select>
                </div>

                <div v-if="!day.attractions || day.attractions.length === 0"
                     style="color:#9ca3af;font-size:13px;padding:14px;background:#f9fafb;border:1px dashed #e5e7eb;border-radius:6px;text-align:center">
                  还没添加景点 — 从上面下拉里选,景点会按选择顺序排成今日路线
                </div>

                <div v-else style="width:100%">
                  <div v-for="(item, i) in day.attractions" :key="i"
                       style="display:flex;align-items:stretch;gap:10px;margin-bottom:6px">

                    <!-- 序号徽章 + 垂直连接线 -->
                    <div style="display:flex;flex-direction:column;align-items:center;min-width:32px;padding-top:8px">
                      <div :style="{
                          width:'28px',height:'28px',borderRadius:'50%',
                          background: i===0 ? '#10b981' : (i===day.attractions.length-1 ? '#ef4444' : '#3b82f6'),
                          color:'white',display:'flex',alignItems:'center',justifyContent:'center',
                          fontWeight:'700',fontSize:'13px',flexShrink:'0',
                          boxShadow:'0 1px 2px rgba(0,0,0,0.15)'
                        }">{{ item.order_index }}</div>
                      <div v-if="i < day.attractions.length - 1"
                           style="width:2px;flex:1;background:#cbd5e1;margin-top:4px;min-height:16px"></div>
                    </div>

                    <!-- 景点信息卡 -->
                    <div style="flex:1;background:#fafbfc;border:1px solid #e5e7eb;border-radius:6px;padding:8px 12px;display:flex;align-items:center;gap:8px">
                      <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:14px;color:#1f2937">
                          <span v-if="i===0" style="color:#10b981;font-size:11px;margin-right:6px">▶ 出发</span>
                          <span v-else-if="i===day.attractions.length-1" style="color:#ef4444;font-size:11px;margin-right:6px">■ 终点</span>
                          {{ filteredAttractions.find(a => a.id === item.attraction_id)?.name_zh || '?' }}
                          <span v-if="filteredAttractions.find(a => a.id === item.attraction_id)?.area"
                                style="color:#6b7280;font-size:12px;font-weight:400;margin-left:6px">
                            📍 {{ filteredAttractions.find(a => a.id === item.attraction_id)?.area }}
                          </span>
                        </div>
                        <div v-for="(t, ti) in attractionConflictTips(day, item)" :key="ti"
                             :style="{ color: t.severity==='error'?'#dc2626':'#d97706', fontSize:'12px', marginTop:'4px' }">
                          {{ t.severity==='error'?'❌':'⚠️' }} 与「{{ t.otherName }}」冲突:{{ t.msg }}
                        </div>
                      </div>

                      <!-- 操作按钮:↑ ↓ × -->
                      <div style="display:flex;gap:4px;flex-shrink:0">
                        <el-button size="small" plain @click="moveAttraction(day, i, -1)"
                                   :disabled="i === 0" title="上移">↑</el-button>
                        <el-button size="small" plain @click="moveAttraction(day, i, 1)"
                                   :disabled="i === day.attractions.length - 1" title="下移">↓</el-button>
                        <el-button size="small" type="danger" plain
                                   @click="removeAttraction(day, i)" title="删除此景点">×</el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </el-form-item>

              <el-row :gutter="12">
                <el-col :xs="12" :md="6">
                  <el-form-item label="午餐">
                    <el-select v-model="day.lunch_restaurant_id" clearable>
                      <el-option v-for="r in filteredRestaurants" :key="r.id" :label="r.name_zh" :value="r.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="12" :md="6">
                  <el-form-item label="晚餐">
                    <el-select v-model="day.dinner_restaurant_id" clearable>
                      <el-option v-for="r in filteredRestaurants" :key="r.id" :label="r.name_zh" :value="r.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="8" :md="4">
                  <el-form-item label="下午茶">
                    <el-select v-model="day.afternoon_tea_id" clearable>
                      <el-option v-for="t in filteredTeas" :key="t.id" :label="t.name_zh" :value="t.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="8" :md="4">
                  <el-form-item label="SPA">
                    <el-select v-model="day.spa_id" clearable>
                      <el-option v-for="s in filteredSpas" :key="s.id" :label="s.name_zh" :value="s.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="8" :md="4">
                  <el-form-item label="水上项目">
                    <el-select v-model="day.water_activity_id" clearable>
                      <el-option v-for="w in filteredWaters" :key="w.id" :label="w.name_zh" :value="w.id" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
            </template>
          </div>
        </div>
        <div style="text-align:center; margin-top:12px;">
          <button type="button" class="btn-day-add" @click="addDay">
            + 添加第 {{ form.days.length + 1 }} 天
          </button>
        </div>
      </div>

      <div class="bws-card" style="text-align:center">
        <el-button type="primary" size="large" @click="saveAndCalculate" :loading="loading">
          💰 生成报价 + 校验 + 赌自费推荐
        </el-button>
      </div>

      <!-- 结果展示 -->
      <div v-if="result" class="summary-card">
        <h3>📊 报价结果 — {{ result.quote_no }}</h3>
        <div class="summary-row"><span class="label">总成本 (IDR)</span><span class="value">{{ fmtNum(result.cost_idr_total) }}</span></div>
        <div class="summary-row"><span class="label">总成本 (CNY)</span><span class="value">¥ {{ fmtNum(result.cost_cny_total) }}</span></div>
        <div class="summary-row"><span class="label">单人利润 (CNY)</span><span class="value">¥ {{ fmtVal(result.profit_cny_per_pax) }}</span></div>
        <div class="summary-row"><span class="label">赌自费让利 (CNY)</span><span class="value" style="color:#f59e0b">¥ -{{ fmtVal(result.gamble_cny_per_pax) }}</span></div>
        <div class="summary-row"><span class="label">单人售价 (CNY)</span><span class="value price">¥ {{ fmtVal(result.price_cny_per_pax) }}</span></div>
        <div class="summary-row"><span class="label">总售价 (CNY)</span><span class="value price">¥ {{ fmtNum(result.price_cny_total) }}</span></div>
      </div>

      <!-- 校验结果 -->
      <div v-if="result?.feasibility_report" class="bws-card">
        <h3>🧭 行程合理性校验
          <el-tag :type="result.feasibility_status === 'pass' ? 'success' : (result.feasibility_status === 'fail' ? 'danger' : 'warning')">
            {{ { pass: '通过', warning: '有警告', fail: '不可行' }[result.feasibility_status] || result.feasibility_status }}
          </el-tag>
        </h3>
        <div v-for="d in result.feasibility_report.days" :key="d.day_index"
             :class="feasibilityClass(d.errors?.length ? 'fail' : (d.warnings?.length ? 'warning' : 'pass'))">
          <strong>Day {{ d.day_index }}</strong> · 总驾驶 {{ d.drive_minutes }} 分钟
          <div v-if="d.errors?.length"><strong style="color:#dc2626">错误：</strong>
            <ul><li v-for="(e,i) in d.errors" :key="i">{{ e }}</li></ul>
          </div>
          <div v-if="d.warnings?.length"><strong style="color:#d97706">警告：</strong>
            <ul><li v-for="(w,i) in d.warnings" :key="i">{{ w }}</li></ul>
          </div>
          <div v-if="d.suggestions?.length"><strong style="color:#1d4ed8">建议：</strong>
            <ul><li v-for="(s,i) in d.suggestions" :key="i">{{ s.description }}</li></ul>
          </div>
        </div>
      </div>

      <!-- 赌自费 -->
      <div v-if="result?.gamble_recommendation" class="gamble-card">
        <h4>💰 赌自费 AI 推荐</h4>

        <!-- v0.5.2: 三种状态分别展示 -->
        <!-- A. 命中 skip 策略 (action=skip) — 真不赌, 可能反向加价 -->
        <el-alert v-if="result.gamble_recommendation.skip_rule && result.gamble_recommendation.skip_rule.action === 'skip'"
                  type="info" :closable="false" show-icon style="margin-bottom:12px">
          <template #title>
            🛡 系统判定:不赌
            <span v-if="result.gamble_recommendation.skip_rule.extra_profit_cny > 0" style="color:#67c23a;font-weight:bold">
              · 反向加 ¥{{ result.gamble_recommendation.skip_rule.extra_profit_cny }}/人 利润
            </span>
          </template>
          <div>命中策略:<strong>{{ result.gamble_recommendation.skip_rule.name }}</strong></div>
          <div style="font-size:12px;color:#6b7280">{{ result.gamble_recommendation.skip_rule.description }}</div>
        </el-alert>

        <!-- B. 命中 fixed/per_pax 策略 — 赌, 让 ¥X/人 -->
        <el-alert v-else-if="result.gamble_recommendation.skip_rule"
                  type="warning" :closable="false" show-icon style="margin-bottom:12px">
          <template #title>
            🎲 系统判定:赌 · 让 ¥{{ result.gamble_recommendation.recommended_cny }}/人
          </template>
          <div>命中策略:<strong>{{ result.gamble_recommendation.skip_rule.name }}</strong></div>
          <div style="font-size:12px;color:#6b7280">{{ result.gamble_recommendation.skip_rule.description }}</div>
        </el-alert>

        <!-- C. 没命中任何策略 + 引擎兜底判定不赌 -->
        <el-alert v-else-if="!result.gamble_recommendation.enabled"
                  type="warning" :closable="false" show-icon style="margin-bottom:12px">
          <template #title>不赌 (无策略命中, 引擎兜底)</template>
          <div>{{ result.gamble_recommendation.reasoning }}</div>
        </el-alert>

        <template v-if="result.gamble_recommendation.enabled">
          <div class="summary-row"><span class="label">推荐让利</span><span class="value price">¥ {{ result.gamble_recommendation.recommended_cny }}/人</span></div>
          <div class="summary-row" v-if="result.gamble_recommendation.low_bound_cny != result.gamble_recommendation.high_bound_cny">
            <span class="label">区间</span><span class="value">¥ {{ result.gamble_recommendation.low_bound_cny }} ~ ¥ {{ result.gamble_recommendation.high_bound_cny }}</span>
          </div>
          <div class="summary-row" v-if="result.gamble_recommendation.ai_confidence">
            <span class="label">AI 信心分</span><span class="value">{{ Math.round((result.gamble_recommendation.ai_confidence||0) * 100) }}%</span>
          </div>
          <div style="margin-top:10px;font-size:13px;color:#6b7280">
            <strong>判断依据:</strong>{{ result.gamble_recommendation.reasoning }}
          </div>
        </template>

        <div v-if="result.gamble_recommendation.configured_optional_tours?.length" style="margin-top:12px">
          <strong>配套自费推荐：</strong>
          <el-table :data="result.gamble_recommendation.configured_optional_tours" size="small" border>
            <el-table-column prop="name" label="项目" />
            <el-table-column prop="category" label="类别" width="100" />
            <el-table-column prop="sale_price_cny" label="售价 ¥" width="90" />
            <el-table-column label="预测购买率" width="120">
              <template #default="s">{{ Math.round(s.row.predicted_purchase_rate * 100) }}%</template>
            </el-table-column>
            <el-table-column prop="expected_revenue_cny" label="期望收入 ¥" width="120" />
          </el-table>
        </div>
        <div v-if="result.gamble_recommendation.excluded_optional_tours?.length" style="margin-top:12px">
          <strong>已排除（行程已覆盖）：</strong>
          <el-table :data="result.gamble_recommendation.excluded_optional_tours" size="small" border>
            <el-table-column prop="name" label="项目" />
            <el-table-column prop="category" label="类别" width="100" />
            <el-table-column prop="exclusion_reason" label="排除原因" />
          </el-table>
        </div>
      </div>

      <!-- 模板详情(每天的"查看模板"按钮触发)-->
      <el-dialog v-model="tplDetailDialog" :title="'模板详情:' + (tplDetail?.name_zh || '')" width="700px">
        <div v-loading="tplDetailLoading">
          <div v-if="tplDetail">
            <p style="margin:0 0 8px;color:#6b7280">
              <el-tag size="small">{{ tplDetail.destination_name }}</el-tag>
              <el-tag size="small" type="info" style="margin-left:6px">{{ tplDetail.difficulty }}</el-tag>
              <span style="margin-left:8px">⏱ 约 {{ tplDetail.total_minutes_estimate }} 分钟</span>
            </p>
            <p v-if="tplDetail.description" style="background:#f9fafb;padding:10px;border-radius:6px">{{ tplDetail.description }}</p>
            <h4 style="margin:14px 0 6px">📍 景点路线</h4>
            <ol style="padding-left:20px;line-height:1.8">
              <li v-for="(a, i) in tplDetail.attractions" :key="i">
                <strong>{{ a.name_zh }}</strong>
                <span v-if="a.area" style="color:#6b7280">（{{ a.area }}）</span>
                <span v-if="a.stay_minutes" style="color:#9ca3af">· 停留 {{ a.stay_minutes }} 分钟</span>
              </li>
            </ol>
            <h4 style="margin:14px 0 6px">🍽 用餐</h4>
            <ul style="padding-left:20px;line-height:1.8">
              <li v-for="(r, i) in tplDetail.restaurants" :key="i">
                <el-tag size="small" :type="r.meal_type==='lunch'?'warning':'primary'">
                  {{ {lunch:'午',dinner:'晚',both:'午/晚'}[r.meal_type] }}
                </el-tag>
                <strong style="margin-left:6px">{{ r.name_zh }}</strong>
              </li>
            </ul>
          </div>
        </div>
        <template #footer>
          <el-button type="primary" @click="tplDetailDialog = false">关闭</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// ============================================================
//  资源库管理 — 9 类资源完整 CRUD + 区域下拉 + 搜索
// ============================================================
const ResourceManager = {
  props: ['destinations'],
  emits: ['refresh'],
  data() {
    return {
      activeKind: 'hotels',
      hotels: [], attractions: [], restaurants: [],
      vehicles: [], guides: [], optionals: [],
      spas: [], waters: [], teas: [],
      loading: false,
      keyword: '',
      areasGrouped: {},
      // 分页
      page: 1,
      pageSize: 10,
      // 各类型独立筛选条件
      filters: {
        hotels:      { star: null, area: null, priceMin: null, priceMax: null, tier: null, propertyType: null },
        attractions: { area: null, priceMin: null, priceMax: null, tier: null },
        restaurants: { area: null, mealType: null, priceMin: null, priceMax: null, tier: null },
        vehicles:    { category: null, seatMin: null, seatMax: null, priceMin: null, priceMax: null, tier: null },
        guides:      { language: null, level: null, priceMin: null, priceMax: null },
        optionals:   { category: null, priceMin: null, priceMax: null, tier: null },
        spas:        { priceMin: null, priceMax: null, tier: null },
        waters:      { priceMin: null, priceMax: null, tier: null },
        teas:        { area: null, priceMin: null, priceMax: null, tier: null },
      },
      // 编辑 dialog
      editDialog: false,
      editForm: {},
      editKind: '',
      saving: false,
    };
  },
  watch: {
    activeKind(v) { this.page = 1; this.load(v); },
    keyword()    { this.page = 1; },
    filters: { deep: true, handler() { this.page = 1; } },
  },
  computed: {
    KIND_META() {
      // 单一来源 — kind → {label, path, listKey, defaults}
      return {
        hotels:      { label: '酒店',     path: '/resources/hotels',         listKey: 'hotels' },
        attractions: { label: '景点',     path: '/resources/attractions',    listKey: 'attractions' },
        restaurants: { label: '餐厅',     path: '/resources/restaurants',    listKey: 'restaurants' },
        vehicles:    { label: '车辆',     path: '/resources/vehicles',       listKey: 'vehicles' },
        guides:      { label: '导游',     path: '/resources/guides',         listKey: 'guides' },
        optionals:   { label: '自费项目', path: '/resources/optional-tours', listKey: 'optionals' },
        spas:        { label: 'SPA',      path: '/resources/simple/spa',     listKey: 'spas',   simpleKind: 'spa'   },
        waters:      { label: '水上项目', path: '/resources/simple/water',   listKey: 'waters', simpleKind: 'water' },
        teas:        { label: '下午茶',   path: '/resources/simple/tea',     listKey: 'teas',   simpleKind: 'tea'   },
      };
    },
    filteredRows() {
      let list = [...(this[this.activeKind] || [])];
      // 全局 keyword
      if (this.keyword) {
        const k = this.keyword.toLowerCase();
        list = list.filter(r => JSON.stringify(r).toLowerCase().includes(k));
      }
      const f = this.filters[this.activeKind] || {};
      const k = this.activeKind;

      // 档位筛选(所有支持档位的类型通用)
      if (f.tier) {
        list = list.filter(r => {
          const t = this.tierOf(k, r);
          return t && t.code === f.tier;
        });
      }

      if (k === 'hotels') {
        if (f.propertyType) list = list.filter(r => this.propertyTypeOf(r).code === f.propertyType);
        if (f.star)  list = list.filter(r => r.star === f.star);
        if (f.area)  list = list.filter(r => r.area === f.area);
        if (f.priceMin != null || f.priceMax != null) {
          list = list.filter(r => {
            if (!r.rooms || !r.rooms.length) return false;
            const minP = Math.min(...r.rooms.map(rm => Number(rm.cost_idr_low) || Infinity));
            if (f.priceMin != null && minP < f.priceMin) return false;
            if (f.priceMax != null && minP > f.priceMax) return false;
            return true;
          });
        }
      } else if (k === 'attractions') {
        if (f.area) list = list.filter(r => r.area === f.area);
        if (f.priceMin != null) list = list.filter(r => Number(r.ticket_idr_adult) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.ticket_idr_adult) <= f.priceMax);
      } else if (k === 'restaurants') {
        if (f.area)     list = list.filter(r => r.area === f.area);
        if (f.mealType) list = list.filter(r => r.meal_type === f.mealType);
        if (f.priceMin != null) list = list.filter(r => Number(r.cost_idr_per_person) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.cost_idr_per_person) <= f.priceMax);
      } else if (k === 'vehicles') {
        if (f.category) {
          list = list.filter(r => {
            const t = (r.vehicle_type || '').toUpperCase();
            if (f.category === 'sedan')  return t.includes('AVANZA') || t.includes('INNOVA') || t.includes('INOVA');
            if (f.category === 'medium') return t.includes('ELF') || t.includes('HIACE');
            if (f.category === 'bus')    return t.includes('巴士') || (r.seat_count || 0) >= 25;
            return true;
          });
        }
        if (f.seatMin != null)  list = list.filter(r => (r.seat_count || 0) >= f.seatMin);
        if (f.seatMax != null)  list = list.filter(r => (r.seat_count || 0) <= f.seatMax);
        if (f.priceMin != null) list = list.filter(r => Number(r.cost_idr_per_day) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.cost_idr_per_day) <= f.priceMax);
      } else if (k === 'guides') {
        if (f.language) list = list.filter(r => r.language === f.language);
        if (f.level)    list = list.filter(r => r.level === f.level);
        if (f.priceMin != null) list = list.filter(r => Number(r.cost_idr_per_day) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.cost_idr_per_day) <= f.priceMax);
      } else if (k === 'optionals') {
        if (f.category) list = list.filter(r => r.category === f.category);
        if (f.priceMin != null) list = list.filter(r => Number(r.sale_price_cny) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.sale_price_cny) <= f.priceMax);
      } else {
        // spas / waters / teas
        if (f.area)             list = list.filter(r => r.area === f.area);
        if (f.priceMin != null) list = list.filter(r => Number(r.cost_idr_per_person) >= f.priceMin);
        if (f.priceMax != null) list = list.filter(r => Number(r.cost_idr_per_person) <= f.priceMax);
      }
      return list;
    },
    paginatedRows() {
      const start = (this.page - 1) * this.pageSize;
      return this.filteredRows.slice(start, start + this.pageSize);
    },
    currentRows() {
      // 兼容旧引用
      return this.paginatedRows;
    },
  },
  // 注:activeKind 触发 load 改用 watch immediate(下方),与上面 page reset watch 合并需小心

  async mounted() {
    try { this.areasGrouped = (await http.get('/settings/areas')).data.grouped || {}; }
    catch (e) { /* 静默 */ }
    this.load(this.activeKind);
  },
  methods: {
    async load(kind) {
      this.loading = true;
      try {
        const r = await http.get(this.KIND_META[kind].path);
        this[this.KIND_META[kind].listKey] = r.data;
      } catch (e) {
        ElementPlus.ElMessage.error('加载失败:' + e.message);
      } finally { this.loading = false; }
    },
    destName(id) {
      return this.destinations?.find(d => d.id === id)?.name_zh || '?';
    },

    // ============ 酒店属性类型(酒店/度假村/别墅)============
    propertyTypeOf(row) {
      const all = `${row.name_zh || ''} ${row.name_en || ''}`.toLowerCase();
      // 别墅类(优先级高 — 含 Villa 即归别墅)
      if (/villa|别墅|pool\s*villa|私人池/i.test(all)) {
        return { code: 'villa',  label: '别墅',   type: 'success' };
      }
      // 度假村/隐世(retreat / sanctuary / 修行 / 度假村)
      if (/resort|度假村|retreat|sanctuary|reserve|隐世|庄园/i.test(all)) {
        return { code: 'resort', label: '度假村', type: 'warning' };
      }
      return     { code: 'hotel',  label: '酒店',   type: 'primary' };
    },

    // ============ 价格档位 (基于母库实际数据分布定阈值) ============
    tierOf(kind, row) {
      if (!row) return null;
      let v = 0;
      if (kind === 'hotels') {
        if (row.rooms?.length) {
          v = Math.min(...row.rooms.map(r => Number(r.cost_idr_low) || Infinity));
          if (!isFinite(v)) return null;
        } else return null;
        if (v < 800000)    return { code:'budget',  label:'经济型',     type:'info'    };
        if (v < 1500000)   return { code:'star4',   label:'国际4星',    type:'primary' };
        if (v < 3000000)   return { code:'star4p',  label:'高端4星',    type:'success' };
        if (v < 6000000)   return { code:'star5',   label:'国际5星',    type:'warning' };
        return                       { code:'luxury',  label:'奢华',       type:'danger'  };
      }
      if (kind === 'attractions') {
        v = Number(row.ticket_idr_adult) || 0;
        if (v < 50000)     return { code:'cheap',  label:'平价',  type:'info'    };
        if (v < 150000)    return { code:'mid',    label:'中端',  type:'primary' };
        return                       { code:'high',   label:'高端',  type:'warning' };
      }
      if (kind === 'restaurants' || kind === 'spas' || kind === 'waters' || kind === 'teas') {
        v = Number(row.cost_idr_per_person) || 0;
        const t1 = (kind === 'restaurants') ? 100000 : 250000;
        const t2 = (kind === 'restaurants') ? 250000 : 500000;
        if (v < t1)        return { code:'cheap',  label:'平价',  type:'info'    };
        if (v < t2)        return { code:'mid',    label:'中端',  type:'primary' };
        return                       { code:'high',   label:'高端',  type:'warning' };
      }
      if (kind === 'vehicles') {
        v = Number(row.cost_idr_per_day) || 0;
        if (v < 500000)    return { code:'eco',    label:'经济',  type:'info'    };
        if (v < 1000000)   return { code:'std',    label:'标准',  type:'primary' };
        if (v < 2000000)   return { code:'biz',    label:'商务',  type:'success' };
        return                       { code:'bus',    label:'大巴',  type:'warning' };
      }
      if (kind === 'optionals') {
        v = Number(row.sale_price_cny) || 0;
        if (v < 300)       return { code:'cheap',  label:'平价',  type:'info'    };
        if (v < 600)       return { code:'mid',    label:'中端',  type:'primary' };
        return                       { code:'high',   label:'高端',  type:'warning' };
      }
      return null;
    },
    tierOptions(kind) {
      // 返回该类型的档位下拉项
      const map = {
        hotels:     [['budget','经济型'],['star4','国际4星'],['star4p','高端4星'],['star5','国际5星'],['luxury','奢华']],
        attractions:[['cheap','平价'],['mid','中端'],['high','高端']],
        restaurants:[['cheap','平价'],['mid','中端'],['high','高端']],
        vehicles:   [['eco','经济'],['std','标准'],['biz','商务'],['bus','大巴']],
        optionals:  [['cheap','平价'],['mid','中端'],['high','高端']],
        spas:       [['cheap','平价'],['mid','中端'],['high','高端']],
        waters:     [['cheap','平价'],['mid','中端'],['high','高端']],
        teas:       [['cheap','平价'],['mid','中端'],['high','高端']],
      };
      return (map[kind] || []).map(([c,l]) => ({ value:c, label:l }));
    },

    // ---- 新增/编辑 ----
    makeEmpty(kind) {
      const did = this.destinations?.[0]?.id || 1;
      const defaults = {
        hotels:      { id:null, destination_id:did, name_zh:'', name_en:'', star:4, area:'', airport_distance_min:30, description:'', rooms:[] },
        attractions: { id:null, destination_id:did, name_zh:'', name_en:'', area:'', ticket_idr_adult:0, ticket_idr_child:0, recommended_minutes:60, has_guide_service:false, restrictions:'' },
        restaurants: { id:null, destination_id:did, name_zh:'', cuisine:'印尼菜', meal_type:'both', area:'', cost_idr_per_person:0, min_pax:1, includes_drink:false, recommended_minutes:60 },
        vehicles:    { id:null, destination_id:did, vehicle_type:'', seat_count:7, cost_idr_per_day:0, includes_fuel:true, includes_driver:true, restrictions:'', max_single_leg_minutes:null, max_daily_minutes:null, terrain_note:'' },
        guides:      { id:null, destination_id:did, name_zh:'', language:'zh', level:'regular', cost_idr_per_day:0, max_pax:null, availability_note:'' },
        optionals:   { id:null, destination_id:did, name_zh:'', sale_price_cny:0, cost_idr:0, margin_cny:0, historical_purchase_rate:0.5, target_audience:'', best_time:'', category:'' },
        spas:        { id:null, destination_id:did, brand:'', package_name:'', duration_minutes:60, cost_idr_per_person:0, includes:'' },
        waters:      { id:null, destination_id:did, name_zh:'', location:'', cost_idr_per_person:0, min_pax:1, max_pax:null, age_limit:'', duration_minutes:60 },
        teas:        { id:null, destination_id:did, name_zh:'', venue:'', area:'', cost_idr_per_person:0, min_pax:1, recommended_minutes:90 },
      };
      return JSON.parse(JSON.stringify(defaults[kind]));
    },
    openCreate() {
      this.editKind = this.activeKind;
      this.editForm = this.makeEmpty(this.activeKind);
      this.editDialog = true;
    },
    openEdit(row) {
      this.editKind = this.activeKind;
      this.editForm = JSON.parse(JSON.stringify(row));
      // hotels 嵌套 rooms
      if (this.activeKind === 'hotels' && !this.editForm.rooms) this.editForm.rooms = [];
      this.editDialog = true;
    },
    addRoom() {
      this.editForm.rooms.push({ id:null, room_type:'Deluxe Room', max_occupancy:2, breakfast_included:true, cost_idr_low:0, cost_idr_high:0, supplier:'', note:'' });
    },
    removeRoom(idx) {
      this.editForm.rooms.splice(idx, 1);
    },
    async saveResource() {
      this.saving = true;
      try {
        const meta = this.KIND_META[this.editKind];
        if (meta.simpleKind) {
          await http.post(`/resources/simple/${meta.simpleKind}`, this.editForm);
        } else {
          await http.post(meta.path, this.editForm);
        }
        ElementPlus.ElMessage.success(this.editForm.id ? '已更新' : '已新增');
        this.editDialog = false;
        await this.load(this.activeKind);
        this.$emit('refresh');
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败:' + (e.response?.data?.detail || e.message));
      } finally {
        this.saving = false;
      }
    },
    async deleteRow(row) {
      if (!confirm(`确认删除 "${row.name_zh || row.vehicle_type || row.package_name || ('#'+row.id)}"?`)) return;
      const meta = this.KIND_META[this.activeKind];
      const url = meta.simpleKind
        ? `/resources/simple/${meta.simpleKind}/${row.id}`
        : `${meta.path}/${row.id}`;
      try {
        await http.delete(url);
        ElementPlus.ElMessage.success('已删除');
        await this.load(this.activeKind);
        this.$emit('refresh');
      } catch (e) {
        ElementPlus.ElMessage.error('删除失败:' + (e.response?.data?.detail || e.message));
      }
    },
  },
  template: `
    <div>
      <el-radio-group v-model="activeKind" style="margin-bottom:16px">
        <el-radio-button v-for="(meta, kind) in KIND_META" :key="kind" :value="kind">{{ meta.label }}</el-radio-button>
      </el-radio-group>

      <div class="bws-card">
        <div style="display:flex;gap:10px;margin-bottom:10px;align-items:center;flex-wrap:wrap">
          <el-input v-model="keyword" placeholder="搜索(任意字段)" style="width:240px" clearable />

          <!-- 酒店 -->
          <template v-if="activeKind==='hotels'">
            <el-select v-model="filters.hotels.propertyType" placeholder="属性" clearable style="width:110px">
              <el-option label="酒店" value="hotel" />
              <el-option label="度假村" value="resort" />
              <el-option label="别墅" value="villa" />
            </el-select>
            <el-select v-model="filters.hotels.star" placeholder="星级" clearable style="width:100px">
              <el-option label="3 星" :value="3" />
              <el-option label="4 星" :value="4" />
              <el-option label="5 星" :value="5" />
            </el-select>
            <el-select v-model="filters.hotels.area" placeholder="区域" filterable clearable style="width:140px">
              <el-option-group v-for="(arr, g) in areasGrouped" :key="g" :label="g">
                <el-option v-for="a in arr" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
            <el-input-number v-model="filters.hotels.priceMin" placeholder="最低价 IDR" :step="100000" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters.hotels.priceMax" placeholder="最高价 IDR" :step="100000" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- 景点 -->
          <template v-else-if="activeKind==='attractions'">
            <el-select v-model="filters.attractions.area" placeholder="区域" filterable clearable style="width:140px">
              <el-option-group v-for="(arr, g) in areasGrouped" :key="g" :label="g">
                <el-option v-for="a in arr" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
            <el-input-number v-model="filters.attractions.priceMin" placeholder="票价≥ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters.attractions.priceMax" placeholder="票价≤ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- 餐厅 -->
          <template v-else-if="activeKind==='restaurants'">
            <el-select v-model="filters.restaurants.mealType" placeholder="餐时" clearable style="width:110px">
              <el-option label="午餐" value="lunch" />
              <el-option label="晚餐" value="dinner" />
              <el-option label="两餐" value="both" />
            </el-select>
            <el-select v-model="filters.restaurants.area" placeholder="区域" filterable clearable style="width:140px">
              <el-option-group v-for="(arr, g) in areasGrouped" :key="g" :label="g">
                <el-option v-for="a in arr" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
            <el-input-number v-model="filters.restaurants.priceMin" placeholder="人均≥ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters.restaurants.priceMax" placeholder="人均≤ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- 车辆 -->
          <template v-else-if="activeKind==='vehicles'">
            <el-select v-model="filters.vehicles.category" placeholder="车型分类" clearable style="width:160px">
              <el-option label="轿车 (Avanza/Innova)" value="sedan" />
              <el-option label="中巴 (Elf/Hiace)" value="medium" />
              <el-option label="大巴 (25 座+)" value="bus" />
            </el-select>
            <el-input-number v-model="filters.vehicles.seatMin" placeholder="座位≥" :min="2" :max="60" controls-position="right" style="width:120px" />
            <el-input-number v-model="filters.vehicles.seatMax" placeholder="座位≤" :min="2" :max="60" controls-position="right" style="width:120px" />
            <el-input-number v-model="filters.vehicles.priceMin" placeholder="日成本≥ IDR" :step="100000" :min="0" controls-position="right" style="width:150px" />
            <el-input-number v-model="filters.vehicles.priceMax" placeholder="日成本≤ IDR" :step="100000" :min="0" controls-position="right" style="width:150px" />
          </template>

          <!-- 导游 -->
          <template v-else-if="activeKind==='guides'">
            <el-select v-model="filters.guides.language" placeholder="语言" clearable style="width:100px">
              <el-option label="中文" value="zh" />
              <el-option label="英文" value="en" />
              <el-option label="印尼" value="id" />
              <el-option label="中+英" value="zh+en" />
            </el-select>
            <el-select v-model="filters.guides.level" placeholder="等级" clearable style="width:100px">
              <el-option label="资深" value="senior" />
              <el-option label="普通" value="regular" />
              <el-option label="实习" value="trainee" />
            </el-select>
            <el-input-number v-model="filters.guides.priceMin" placeholder="日成本≥ IDR" :step="50000" :min="0" controls-position="right" style="width:150px" />
            <el-input-number v-model="filters.guides.priceMax" placeholder="日成本≤ IDR" :step="50000" :min="0" controls-position="right" style="width:150px" />
          </template>

          <!-- 自费 -->
          <template v-else-if="activeKind==='optionals'">
            <el-select v-model="filters.optionals.category" placeholder="类别" clearable style="width:140px">
              <el-option v-for="c in ['spa','sunset','sunrise','food_upgrade','performance','water','shopping','temple','shows','island_trip']" :key="c" :label="c" :value="c" />
            </el-select>
            <el-input-number v-model="filters.optionals.priceMin" placeholder="售价≥ ¥" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters.optionals.priceMax" placeholder="售价≤ ¥" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- 下午茶 -->
          <template v-else-if="activeKind==='teas'">
            <el-select v-model="filters.teas.area" placeholder="区域" filterable clearable style="width:140px">
              <el-option-group v-for="(arr, g) in areasGrouped" :key="g" :label="g">
                <el-option v-for="a in arr" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
            <el-input-number v-model="filters.teas.priceMin" placeholder="人均≥ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters.teas.priceMax" placeholder="人均≤ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- SPA / 水上 -->
          <template v-else>
            <el-input-number v-model="filters[activeKind].priceMin" placeholder="人均≥ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
            <el-input-number v-model="filters[activeKind].priceMax" placeholder="人均≤ IDR" :step="50000" :min="0" controls-position="right" style="width:140px" />
          </template>

          <!-- 价格档位筛选(所有类型通用,导游除外)-->
          <el-select v-if="activeKind!=='guides'" v-model="filters[activeKind].tier"
                     placeholder="价格档位" clearable style="width:130px">
            <el-option v-for="o in tierOptions(activeKind)" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>

          <span style="color:#6b7280;font-size:13px">筛后 {{ filteredRows.length }} 条 / 总 {{ (this[activeKind]||[]).length }}</span>
          <div style="margin-left:auto">
            <el-button type="primary" @click="openCreate">+ 新增{{ KIND_META[activeKind].label }}</el-button>
          </div>
        </div>

        <!-- 酒店表 -->
        <el-table v-if="activeKind==='hotels'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="名称" />
          <el-table-column prop="name_en" label="英文" width="180" />
          <el-table-column label="属性" width="80">
            <template #default="s">
              <el-tag :type="propertyTypeOf(s.row).type" size="small">{{ propertyTypeOf(s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="档位" width="100">
            <template #default="s">
              <el-tag v-if="tierOf('hotels', s.row)" :type="tierOf('hotels', s.row).type" size="small">
                {{ tierOf('hotels', s.row).label }}
              </el-tag>
              <span v-else style="color:#9ca3af">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="star" label="星级" width="70" />
          <el-table-column prop="area" label="区域" width="120" />
          <el-table-column label="房型数" width="80">
            <template #default="s">{{ s.row.rooms?.length || 0 }}</template>
          </el-table-column>
          <el-table-column label="房价区间" width="170">
            <template #default="s">
              <span v-if="s.row.rooms?.length" style="color:#dc2626">
                {{ Math.min(...s.row.rooms.map(r => r.cost_idr_low || 0)).toLocaleString() }} ~
                {{ Math.max(...s.row.rooms.map(r => r.cost_idr_high || 0)).toLocaleString() }} IDR
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 景点表 -->
        <el-table v-else-if="activeKind==='attractions'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="名称" />
          <el-table-column label="档位" width="80">
            <template #default="s">
              <el-tag :type="tierOf('attractions', s.row).type" size="small">{{ tierOf('attractions', s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="area" label="区域" width="120" />
          <el-table-column prop="ticket_idr_adult" label="成人票 IDR" width="120">
            <template #default="s">{{ Number(s.row.ticket_idr_adult).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="ticket_idr_child" label="儿童 IDR" width="110">
            <template #default="s">{{ Number(s.row.ticket_idr_child).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="recommended_minutes" label="建议停留" width="100" />
          <el-table-column prop="restrictions" label="备注" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 餐厅表 -->
        <el-table v-else-if="activeKind==='restaurants'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="名称" />
          <el-table-column label="档位" width="80">
            <template #default="s">
              <el-tag :type="tierOf('restaurants', s.row).type" size="small">{{ tierOf('restaurants', s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="cuisine" label="菜系" width="90" />
          <el-table-column label="餐时" width="90">
            <template #default="s">{{ {lunch:'午',dinner:'晚',both:'午+晚'}[s.row.meal_type] }}</template>
          </el-table-column>
          <el-table-column prop="area" label="区域" width="120" />
          <el-table-column prop="cost_idr_per_person" label="人均 IDR" width="120">
            <template #default="s">{{ Number(s.row.cost_idr_per_person).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="min_pax" label="起订人数" width="90" />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 车辆表 -->
        <el-table v-else-if="activeKind==='vehicles'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="vehicle_type" label="车型" />
          <el-table-column label="档位" width="80">
            <template #default="s">
              <el-tag :type="tierOf('vehicles', s.row).type" size="small">{{ tierOf('vehicles', s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="seat_count" label="座位" width="80" />
          <el-table-column prop="cost_idr_per_day" label="日成本 IDR" width="130">
            <template #default="s">{{ Number(s.row.cost_idr_per_day).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column label="含油/含司" width="120">
            <template #default="s">
              <el-tag size="small" :type="s.row.includes_fuel?'success':'info'">{{ s.row.includes_fuel?'含油':'裸车' }}</el-tag>
              <el-tag size="small" :type="s.row.includes_driver?'success':'info'" style="margin-left:4px">{{ s.row.includes_driver?'含司':'无司' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="terrain_note" label="地形限制" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 导游表 -->
        <el-table v-else-if="activeKind==='guides'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="姓名" />
          <el-table-column label="语言" width="100">
            <template #default="s">{{ {zh:'中文',en:'英文',id:'印尼',
              'zh+en':'中英'}[s.row.language] || s.row.language }}</template>
          </el-table-column>
          <el-table-column label="等级" width="100">
            <template #default="s">{{ {senior:'资深',regular:'普通',trainee:'实习'}[s.row.level] || s.row.level }}</template>
          </el-table-column>
          <el-table-column prop="cost_idr_per_day" label="日成本 IDR" width="130">
            <template #default="s">{{ Number(s.row.cost_idr_per_day).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="max_pax" label="最大带团" width="100" />
          <el-table-column prop="availability_note" label="备注" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 自费项目表 -->
        <el-table v-else-if="activeKind==='optionals'" :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="名称" />
          <el-table-column label="档位" width="80">
            <template #default="s">
              <el-tag :type="tierOf('optionals', s.row).type" size="small">{{ tierOf('optionals', s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="category" label="类别" width="100" />
          <el-table-column prop="sale_price_cny" label="售价 ¥" width="100" />
          <el-table-column prop="cost_idr" label="成本 IDR" width="120">
            <template #default="s">{{ Number(s.row.cost_idr).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="margin_cny" label="毛利 ¥" width="100" />
          <el-table-column prop="historical_purchase_rate" label="历史购买率" width="110">
            <template #default="s">{{ Math.round(s.row.historical_purchase_rate*100) }}%</template>
          </el-table-column>
          <el-table-column prop="target_audience" label="目标客群" min-width="120" />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- SPA / 水上 / 下午茶(简单结构通用) -->
        <el-table v-else :data="currentRows" v-loading="loading" border stripe size="small">
          <el-table-column type="index" width="50" />
          <el-table-column prop="name_zh" label="名称" />
          <el-table-column label="档位" width="80">
            <template #default="s">
              <el-tag :type="tierOf(activeKind, s.row).type" size="small">{{ tierOf(activeKind, s.row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="activeKind==='spas'" prop="brand" label="品牌" width="120" />
          <el-table-column v-if="activeKind==='waters'" prop="location" label="地点" width="120" />
          <el-table-column v-if="activeKind==='teas'" prop="venue" label="场所" width="120" />
          <el-table-column v-if="activeKind==='teas'" prop="area" label="区域" width="120" />
          <el-table-column prop="duration_minutes" label="时长(分钟)" width="100" />
          <el-table-column prop="cost_idr_per_person" label="人均 IDR" width="130">
            <template #default="s">{{ Number(s.row.cost_idr_per_person).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column v-if="activeKind!=='teas'" prop="min_pax" label="最少人数" width="90" />
          <el-table-column v-if="activeKind==='waters'" prop="age_limit" label="年龄限制" width="100" />
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteRow(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页 -->
        <div style="margin-top:14px;display:flex;justify-content:flex-end">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20]"
            :total="filteredRows.length"
            layout="total, sizes, prev, pager, next, jumper"
            background />
        </div>
      </div>

      <!-- 编辑/新增 dialog (按 kind 渲染不同字段) -->
      <el-dialog v-model="editDialog"
                 :title="(editForm.id?'编辑':'新增') + KIND_META[editKind]?.label"
                 :width="editKind==='hotels' ? '900px' : '700px'">
        <el-form label-width="100px">
          <el-form-item label="目的地" required>
            <el-select v-model="editForm.destination_id" style="width:100%">
              <el-option v-for="d in destinations" :key="d.id" :label="d.name_zh" :value="d.id" />
            </el-select>
          </el-form-item>

          <!-- ===== 酒店 ===== -->
          <template v-if="editKind==='hotels'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="中文名" required><el-input v-model="editForm.name_zh" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="英文名"><el-input v-model="editForm.name_en" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="6"><el-form-item label="星级"><el-input-number v-model="editForm.star" :min="0" :max="5" /></el-form-item></el-col>
              <el-col :span="9">
                <el-form-item label="区域">
                  <el-select v-model="editForm.area" filterable clearable style="width:100%">
                    <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                      <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
                    </el-option-group>
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="9"><el-form-item label="到机场(分)"><el-input-number v-model="editForm.airport_distance_min" :min="0" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="描述"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
            <el-divider>房型 ({{ editForm.rooms?.length || 0 }})</el-divider>
            <div v-for="(rm, i) in editForm.rooms" :key="i" style="display:flex;gap:6px;margin-bottom:6px;align-items:center;flex-wrap:wrap">
              <el-input v-model="rm.room_type" placeholder="房型" style="width:140px" size="small" />
              <el-input-number v-model="rm.max_occupancy" :min="1" :max="6" size="small" controls-position="right" style="width:90px" />
              <el-input-number v-model="rm.cost_idr_low" :min="0" :step="100000" placeholder="淡季" size="small" controls-position="right" style="width:130px" />
              <el-input-number v-model="rm.cost_idr_high" :min="0" :step="100000" placeholder="旺季" size="small" controls-position="right" style="width:130px" />
              <el-checkbox v-model="rm.breakfast_included">含早</el-checkbox>
              <el-input v-model="rm.supplier" placeholder="供应商" size="small" style="width:120px" />
              <el-input v-model="rm.note" placeholder="备注" size="small" style="width:140px" />
              <el-button size="small" type="danger" link @click="removeRoom(i)">删除</el-button>
            </div>
            <el-button size="small" plain @click="addRoom">+ 添加房型</el-button>
          </template>

          <!-- ===== 景点 ===== -->
          <template v-else-if="editKind==='attractions'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="中文名" required><el-input v-model="editForm.name_zh" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="英文名"><el-input v-model="editForm.name_en" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="区域">
                  <el-select v-model="editForm.area" filterable clearable style="width:100%">
                    <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                      <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
                    </el-option-group>
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12"><el-form-item label="建议停留(分)"><el-input-number v-model="editForm.recommended_minutes" :step="15" :min="15" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="成人票 IDR"><el-input-number v-model="editForm.ticket_idr_adult" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="儿童票 IDR"><el-input-number v-model="editForm.ticket_idr_child" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="提供讲解"><el-switch v-model="editForm.has_guide_service" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="editForm.restrictions" type="textarea" :rows="2" placeholder="如:周日闭馆 / 限身高 110cm 以上" /></el-form-item>
          </template>

          <!-- ===== 餐厅 ===== -->
          <template v-else-if="editKind==='restaurants'">
            <el-form-item label="中文名" required><el-input v-model="editForm.name_zh" /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="8"><el-form-item label="菜系"><el-input v-model="editForm.cuisine" placeholder="印尼菜/中餐/西餐" /></el-form-item></el-col>
              <el-col :span="8">
                <el-form-item label="餐时">
                  <el-radio-group v-model="editForm.meal_type">
                    <el-radio-button value="lunch">午</el-radio-button>
                    <el-radio-button value="dinner">晚</el-radio-button>
                    <el-radio-button value="both">两餐</el-radio-button>
                  </el-radio-group>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="区域">
                  <el-select v-model="editForm.area" filterable clearable style="width:100%">
                    <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                      <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
                    </el-option-group>
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="8"><el-form-item label="人均 IDR"><el-input-number v-model="editForm.cost_idr_per_person" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="起订人数"><el-input-number v-model="editForm.min_pax" :min="1" /></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="含饮料"><el-switch v-model="editForm.includes_drink" /></el-form-item></el-col>
            </el-row>
          </template>

          <!-- ===== 车辆 ===== -->
          <template v-else-if="editKind==='vehicles'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="车型" required><el-input v-model="editForm.vehicle_type" placeholder="Toyota Hiace / Avanza" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="座位"><el-input-number v-model="editForm.seat_count" :min="2" :max="55" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="日成本 IDR"><el-input-number v-model="editForm.cost_idr_per_day" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="6"><el-form-item label="含油"><el-switch v-model="editForm.includes_fuel" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="含司机"><el-switch v-model="editForm.includes_driver" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="单段上限(分)"><el-input-number v-model="editForm.max_single_leg_minutes" :min="0" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="全天上限(分)"><el-input-number v-model="editForm.max_daily_minutes" :min="0" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="禁入区域"><el-input v-model="editForm.restrictions" placeholder='JSON 数组,如: ["Monkey Forest","Canggu"]' /></el-form-item>
            <el-form-item label="地形说明"><el-input v-model="editForm.terrain_note" type="textarea" :rows="2" placeholder="如:山路通行受限,雨天慎行" /></el-form-item>
          </template>

          <!-- ===== 导游 ===== -->
          <template v-else-if="editKind==='guides'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="姓名" required><el-input v-model="editForm.name_zh" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="日成本 IDR"><el-input-number v-model="editForm.cost_idr_per_day" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="语言">
                  <el-select v-model="editForm.language" style="width:100%">
                    <el-option label="中文" value="zh" />
                    <el-option label="英文" value="en" />
                    <el-option label="印尼语" value="id" />
                    <el-option label="中+英" value="zh+en" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="等级">
                  <el-select v-model="editForm.level" style="width:100%">
                    <el-option label="资深" value="senior" />
                    <el-option label="普通" value="regular" />
                    <el-option label="实习" value="trainee" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8"><el-form-item label="最大带团"><el-input-number v-model="editForm.max_pax" :min="1" :max="50" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="备注"><el-input v-model="editForm.availability_note" type="textarea" :rows="2" placeholder="如:仅 2-3 人小团 / 周末不可" /></el-form-item>
          </template>

          <!-- ===== 自费项目 ===== -->
          <template v-else-if="editKind==='optionals'">
            <el-form-item label="名称" required><el-input v-model="editForm.name_zh" /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="6"><el-form-item label="售价 ¥"><el-input-number v-model="editForm.sale_price_cny" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="成本 IDR"><el-input-number v-model="editForm.cost_idr" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="毛利 ¥"><el-input-number v-model="editForm.margin_cny" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="6">
                <el-form-item label="历史购买率">
                  <el-input-number v-model="editForm.historical_purchase_rate" :step="0.05" :precision="2" :min="0" :max="1" style="width:100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="类别">
                  <el-select v-model="editForm.category" clearable style="width:100%">
                    <el-option v-for="c in ['spa','sunset','sunrise','food_upgrade','performance','water','shopping','temple','shows','island_trip']" :key="c" :label="c" :value="c" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12"><el-form-item label="目标客群"><el-input v-model="editForm.target_audience" placeholder="如:蜜月/亲子/老年" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="最佳时间"><el-input v-model="editForm.best_time" placeholder="如:旺季傍晚" /></el-form-item>
          </template>

          <!-- ===== SPA ===== -->
          <template v-else-if="editKind==='spas'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="品牌"><el-input v-model="editForm.brand" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="套餐名" required><el-input v-model="editForm.package_name" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="时长(分)"><el-input-number v-model="editForm.duration_minutes" :step="15" :min="30" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="人均 IDR"><el-input-number v-model="editForm.cost_idr_per_person" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="包含项目"><el-input v-model="editForm.includes" type="textarea" :rows="3" placeholder="按摩 + 花瓣浴 + 茶点" /></el-form-item>
          </template>

          <!-- ===== 水上 ===== -->
          <template v-else-if="editKind==='waters'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="名称" required><el-input v-model="editForm.name_zh" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="地点"><el-input v-model="editForm.location" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="6"><el-form-item label="人均 IDR"><el-input-number v-model="editForm.cost_idr_per_person" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="时长(分)"><el-input-number v-model="editForm.duration_minutes" :step="15" :min="15" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="最少人数"><el-input-number v-model="editForm.min_pax" :min="1" /></el-form-item></el-col>
              <el-col :span="6"><el-form-item label="最多人数"><el-input-number v-model="editForm.max_pax" :min="1" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="年龄限制"><el-input v-model="editForm.age_limit" placeholder="如:6 岁以上 / 12 岁以上需家长同意" /></el-form-item>
          </template>

          <!-- ===== 下午茶 ===== -->
          <template v-else-if="editKind==='teas'">
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="名称" required><el-input v-model="editForm.name_zh" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="场所"><el-input v-model="editForm.venue" placeholder="如:四季悬崖" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="区域">
                  <el-select v-model="editForm.area" filterable clearable style="width:100%">
                    <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                      <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
                    </el-option-group>
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8"><el-form-item label="人均 IDR"><el-input-number v-model="editForm.cost_idr_per_person" :step="50000" :min="0" style="width:100%" /></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="最少人数"><el-input-number v-model="editForm.min_pax" :min="1" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="建议停留(分)"><el-input-number v-model="editForm.recommended_minutes" :step="15" :min="30" /></el-form-item>
          </template>
        </el-form>
        <template #footer>
          <el-button @click="editDialog = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveResource">保存</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// ============================================================
//  AI 文档上传
// ============================================================
const AiUploader = {
  emits: ['confirmed'],
  data() {
    return {
      file: null,
      hint: '',
      uploading: false,
      result: null,
      selectedRows: [],
      areasGrouped: {},
      // ===== v0.6 客户行程一键报价 =====
      itinFile: null,
      itinHint: '',
      itinUploading: false,
      itinResult: null,         // {quote_draft, missing_fields, match_log, ...}
      itinFillerVisible: false, // 补漏 dialog
      itinFillerForm: {},       // 用户在补漏表单填的值
      itinHotels: [],
      itinVehicles: [],
      itinDestinations: [],
      itinSubmitting: false,
    };
  },
  async mounted() {
    try {
      this.areasGrouped = (await http.get('/settings/areas')).data.grouped || {};
    } catch (e) { /* 拉不到时下拉为空,但不报错 */ }
    // v0.6 预加载资源给补漏下拉用
    try {
      this.itinHotels = (await http.get('/resources/hotels')).data || [];
      this.itinVehicles = (await http.get('/resources/vehicles')).data || [];
      this.itinDestinations = (await http.get('/resources/destinations')).data || [];
    } catch (e) {}
  },
  methods: {
    handleChange(file) {
      this.file = file.raw;
    },
    typeOptions() {
      return [
        { v: 'hotel_room',     l: '酒店房型' },
        { v: 'attraction',     l: '景点' },
        { v: 'restaurant',     l: '餐厅' },
        { v: 'vehicle',        l: '车辆' },
        { v: 'guide',          l: '导游' },
        { v: 'spa',            l: 'SPA' },
        { v: 'water_activity', l: '水上项目' },
        { v: 'afternoon_tea',  l: '下午茶' },
        { v: 'optional_tour',  l: '自费项目' },
      ];
    },
    nameField(rtype) {
      return ({ hotel_room: 'room_type', vehicle: 'vehicle_type' })[rtype] || 'name_zh';
    },
    priceField(rtype) {
      return ({
        hotel_room:     'cost_idr_low',
        attraction:     'ticket_idr_adult',
        restaurant:     'cost_idr_per_person',
        vehicle:        'cost_idr_per_day',
        guide:          'cost_idr_per_day',
        spa:            'cost_idr_per_person',
        water_activity: 'cost_idr_per_person',
        afternoon_tea:  'cost_idr_per_person',
        optional_tour:  'cost_idr',
      })[rtype] || 'cost_idr';
    },
    getName(row) { return row.data?.[this.nameField(row.resource_type)] || ''; },
    setName(row, v) {
      if (!row.data) row.data = {};
      row.data[this.nameField(row.resource_type)] = v;
    },
    getHotelName(row) { return row.data?.hotel_name_zh || ''; },
    setHotelName(row, v) {
      if (!row.data) row.data = {};
      row.data.hotel_name_zh = v;
    },
    getPrice(row) {
      const v = row.data?.[this.priceField(row.resource_type)];
      return (v === undefined || v === null || v === '') ? 0 : Number(v);
    },
    setPrice(row, v) {
      if (!row.data) row.data = {};
      row.data[this.priceField(row.resource_type)] = v;
    },
    getNote(row) { return row.data?.note || ''; },
    setNote(row, v) {
      if (!row.data) row.data = {};
      row.data.note = v;
    },
    getArea(row) { return row.data?.area || ''; },
    setArea(row, v) {
      if (!row.data) row.data = {};
      row.data.area = v;
    },
    needsArea(rtype) {
      // 仅这三类资源有 area 字段(对应 model 列)
      return ['hotel_room', 'attraction', 'restaurant'].includes(rtype);
    },
    addRow() {
      if (!this.result) this.result = { resources: [], extraction_id: null };
      this.result.resources.push({
        resource_type: 'hotel_room',
        confidence: 1,
        data: { destination_code: 'DPS' },
        _manual: true,
      });
    },
    removeRow(idx) {
      this.result.resources.splice(idx, 1);
    },
    async uploadAndParse() {
      if (!this.file) {
        ElementPlus.ElMessage.warning('请选择文件');
        return;
      }
      this.uploading = true;
      const fd = new FormData();
      fd.append('file', this.file);
      if (this.hint) fd.append('hint', this.hint);
      try {
        const r = await http.post('/ai/parse', fd, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        this.result = r.data;
        ElementPlus.ElMessage.success(`识别到 ${r.data.resources?.length || 0} 条资源`);
      } catch (e) {
        ElementPlus.ElMessage.error('解析失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.uploading = false;
      }
    },
    async confirm() {
      if (!this.result) return;
      const confirmed = (this.selectedRows.length ? this.selectedRows : this.result.resources)
        .map(r => ({ resource_type: r.resource_type, data: r.data }));
      try {
        const r = await http.post(`/ai/extractions/${this.result.extraction_id}/confirm`, {
          confirmed_resources: confirmed,
          corrections: []
        });
        const okCount = r.data.inserted.filter(x => x.id).length;
        const failCount = r.data.inserted.length - okCount;
        let msg = `已入库 ${okCount} 条`;
        if (failCount) msg += ` · 失败 ${failCount} 条`;
        ElementPlus.ElMessage.success(msg);
        if (r.data.notes_dropped?.length) {
          const types = [...new Set(r.data.notes_dropped)].join('/');
          ElementPlus.ElMessage.warning(`提示:${types} 类型没有备注列,备注未保存`);
        }
        this.$emit('confirmed');
        this.result = null;
        this.file = null;
      } catch (e) {
        ElementPlus.ElMessage.error('入库失败：' + (e.response?.data?.detail || e.message));
      }
    },

    // ===== v0.6 客户行程一键报价 =====
    handleItinChange(file) {
      this.itinFile = file.raw;
    },
    async parseItinerary() {
      if (!this.itinFile) return;
      this.itinUploading = true;
      this.itinResult = null;
      try {
        const fd = new FormData();
        fd.append('file', this.itinFile);
        if (this.itinHint) fd.append('hint', this.itinHint);
        const r = await http.post('/ai/parse-itinerary', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 120000,
        });
        this.itinResult = r.data;
        // 把 quote_draft 字段填入补漏表单(用户可以改)
        const d = r.data.quote_draft || {};
        this.itinFillerForm = {
          agency_name: d.agency_name || '',
          customer_name: d.customer_name || '',
          pax_adult: d.pax_adult || 2,
          pax_child: d.pax_child || 0,
          pax_senior: d.pax_senior || 0,
          start_date: d.start_date || null,
          end_date: d.end_date || null,
          destination_codes: d.destination_codes || ['DPS'],
          season: d.season || 'shoulder',
          customer_type: d.customer_type || 'family',
          notes: d.notes || '',
        };
        // 弹补漏 dialog
        this.itinFillerVisible = true;
        ElementPlus.ElMessage.success(`AI 解析完成 · 信心 ${Math.round((r.data.ai_confidence || 0) * 100)}% · 缺 ${r.data.missing_fields.length} 项需补漏`);
      } catch (e) {
        ElementPlus.ElMessage.error('AI 解析失败: ' + (e.response?.data?.detail || e.message));
      } finally {
        this.itinUploading = false;
      }
    },
    async submitItinerary() {
      // 把 filler 表单合并回 quote_draft
      this.itinSubmitting = true;
      try {
        const draft = JSON.parse(JSON.stringify(this.itinResult.quote_draft));
        Object.assign(draft, this.itinFillerForm);
        // 若用户在补漏里改了 days[i] 字段, 也合并回 (简化: 保留 AI 的 days)
        const r = await http.post('/ai/quote-from-itinerary', { quote_draft: draft });
        ElementPlus.ElMessage.success(`✓ 报价已生成 ${r.data.quote_no} · 总价 ¥${r.data.calculate.price_cny_total} · 单人 ¥${r.data.calculate.price_cny_per_pax}`);
        this.itinFillerVisible = false;
        this.itinResult = null;
        this.itinFile = null;
        // 触发父组件刷新报价历史
        this.$emit('confirmed');
      } catch (e) {
        ElementPlus.ElMessage.error('生成报价失败: ' + (e.response?.data?.detail || e.message));
      } finally {
        this.itinSubmitting = false;
      }
    },
    cancelItinerary() {
      this.itinFillerVisible = false;
      this.itinResult = null;
      this.itinFile = null;
    }
  },
  template: `
    <div>
      <!-- v0.6 客户行程一键报价 (放最上面) -->
      <div class="bws-card" style="border:2px solid #67c23a">
        <h3>⚡ 客户行程 → 一键 AI 报价 <el-tag type="success" size="small" style="margin-left:8px">v0.6 新</el-tag></h3>
        <p style="color:#6b7280;margin-top:0">
          客户把"我想要的行程"发来 (PDF/Word/Excel/图片), 上传 → AI 抽出意向 → 自动匹配资源库 → 弹表单让你补全缺失的人数/日期/儿童/老年等 → 一键算价
        </p>
        <el-row :gutter="16">
          <el-col :span="16">
            <el-upload drag :auto-upload="false" :on-change="handleItinChange" :show-file-list="true" :limit="1"
                       accept=".pdf,.docx,.xlsx,.xls,.png,.jpg,.jpeg,.webp">
              <el-icon class="el-icon--upload" style="font-size:48px;color:#67c23a"><upload-filled /></el-icon>
              <div class="el-upload__text">拖拽客户的行程文件,或<em>点击上传</em></div>
              <template #tip>
                <div class="el-upload__tip">支持: PDF / DOCX / Excel / PNG/JPG · AI 会自动抽出"成人/儿童/日期/酒店/景点"等</div>
              </template>
            </el-upload>
          </el-col>
          <el-col :span="8">
            <el-form-item label="补充提示 (可选)">
              <el-input v-model="itinHint" type="textarea" :rows="3" placeholder="如: 蜜月团, 6 月去, 想住五星海景房, 1 大 1 孩" />
            </el-form-item>
            <el-button type="success" @click="parseItinerary" :loading="itinUploading" :disabled="!itinFile" style="width:100%">
              ⚡ AI 解析 + 一键报价
            </el-button>
          </el-col>
        </el-row>
      </div>

      <!-- 补漏 dialog -->
      <el-dialog v-model="itinFillerVisible" title="📝 补漏 — 完善缺失信息后一键生成报价" width="780px" :close-on-click-modal="false">
        <div v-if="itinResult">
          <el-alert v-if="itinResult.extraction_summary" type="info" :closable="false" style="margin-bottom:12px">
            <template #title>AI 解析摘要 · 信心 {{ Math.round((itinResult.ai_confidence||0)*100) }}%</template>
            <div>{{ itinResult.extraction_summary }}</div>
          </el-alert>
          <el-alert v-if="itinResult.warnings?.length" type="warning" :closable="false" style="margin-bottom:12px">
            <template #title>⚠ AI 警告</template>
            <ul style="margin:6px 0 0;padding-left:18px">
              <li v-for="(w,i) in itinResult.warnings" :key="i">{{ w }}</li>
            </ul>
          </el-alert>

          <h4 style="margin:0 0 8px;color:#1e2761">基本信息 (AI 已填, 你可改)</h4>
          <el-form :model="itinFillerForm" label-width="120px" label-position="left" inline>
            <el-form-item label="B 端旅行社">
              <el-input v-model="itinFillerForm.agency_name" placeholder="如: 上海康辉" style="width:240px" />
            </el-form-item>
            <el-form-item label="客户名称">
              <el-input v-model="itinFillerForm.customer_name" placeholder="如: 张三蜜月团" style="width:240px" />
            </el-form-item>
            <el-form-item label="出发日期">
              <el-date-picker v-model="itinFillerForm.start_date" type="date" value-format="YYYY-MM-DD" style="width:160px" />
            </el-form-item>
            <el-form-item label="结束日期">
              <el-date-picker v-model="itinFillerForm.end_date" type="date" value-format="YYYY-MM-DD" style="width:160px" />
            </el-form-item>
            <el-form-item label="成人">
              <el-input-number v-model="itinFillerForm.pax_adult" :min="1" :max="50" />
            </el-form-item>
            <el-form-item label="儿童">
              <el-input-number v-model="itinFillerForm.pax_child" :min="0" :max="20" />
            </el-form-item>
            <el-form-item label="长者">
              <el-input-number v-model="itinFillerForm.pax_senior" :min="0" :max="50" />
            </el-form-item>
            <el-form-item label="客户类型">
              <el-select v-model="itinFillerForm.customer_type" style="width:140px">
                <el-option label="蜜月" value="honeymoon" />
                <el-option label="婚礼" value="wedding" />
                <el-option label="亲子" value="family_kids" />
                <el-option label="年轻人" value="young" />
                <el-option label="家庭" value="family" />
                <el-option label="长辈" value="senior" />
                <el-option label="MICE" value="mice" />
              </el-select>
            </el-form-item>
            <el-form-item label="季节">
              <el-select v-model="itinFillerForm.season" style="width:100px">
                <el-option label="淡季" value="low" />
                <el-option label="平季" value="shoulder" />
                <el-option label="旺季" value="high" />
              </el-select>
            </el-form-item>
            <el-form-item label="目的地">
              <el-select v-model="itinFillerForm.destination_codes" multiple collapse-tags style="width:220px">
                <el-option v-for="d in itinDestinations" :key="d.code" :label="d.name_zh" :value="d.code" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="itinFillerForm.notes" type="textarea" :rows="2" style="width:520px" />
            </el-form-item>
          </el-form>

          <el-divider>📋 缺失字段提示 (后端检测出 {{ itinResult.missing_fields?.length || 0 }} 项)</el-divider>
          <el-table v-if="itinResult.missing_fields?.length" :data="itinResult.missing_fields" size="small" border max-height="200">
            <el-table-column prop="field" label="字段" width="240" />
            <el-table-column prop="label" label="说明" />
            <el-table-column label="必填" width="60">
              <template #default="s">
                <el-tag v-if="s.row.required" type="danger" size="small">必填</el-tag>
                <el-tag v-else type="info" size="small">可选</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <p v-else style="color:#67c23a;text-align:center">✓ AI 已抽出所有关键信息, 直接提交即可</p>

          <el-divider>🔍 AI 资源匹配日志 ({{ itinResult.match_log?.length || 0 }} 条)</el-divider>
          <el-table v-if="itinResult.match_log?.length" :data="itinResult.match_log" size="small" border max-height="200">
            <el-table-column prop="day_index" label="天" width="50" />
            <el-table-column prop="kind" label="类别" width="80" />
            <el-table-column prop="query" label="AI 抽出的文字" min-width="160" />
            <el-table-column prop="matched_name" label="匹配到的资源" min-width="160" />
            <el-table-column label="匹配度" width="100">
              <template #default="s">
                <el-tag :type="s.row.score >= 0.7 ? 'success' : (s.row.score >= 0.5 ? 'warning' : 'danger')" size="small">
                  {{ Math.round(s.row.score * 100) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="采用" width="60">
              <template #default="s">
                <el-icon v-if="s.row.accepted" style="color:#67c23a"><check /></el-icon>
                <el-icon v-else style="color:#f56c6c"><close /></el-icon>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <template #footer>
          <el-button @click="cancelItinerary">取消</el-button>
          <el-button type="success" :loading="itinSubmitting" @click="submitItinerary">
            ⚡ 一键生成报价 (含算价)
          </el-button>
        </template>
      </el-dialog>

      <!-- 老的供应商资源采集 (保留) -->
      <div class="bws-card">
        <h3>🤖 AI 文档智能采集</h3>
        <p style="color:#6b7280;margin-top:0">支持 PDF / DOCX / Excel / 图片. 上传供应商发的报价文件, AI 自动提取酒店/景点/车辆等成本数据.</p>

        <el-row :gutter="16">
          <el-col :span="16">
            <el-upload
              drag
              :auto-upload="false"
              :on-change="handleChange"
              :show-file-list="true"
              :limit="1"
              accept=".pdf,.docx,.xlsx,.xls,.png,.jpg,.jpeg,.webp">
              <el-icon class="el-icon--upload" style="font-size:48px;color:#1e2761"><upload-filled /></el-icon>
              <div class="el-upload__text">
                拖拽文件到此处，或<em>点击上传</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  支持: PDF / DOCX / Excel / PNG/JPG. 单文件 ≤ 10MB
                </div>
              </template>
            </el-upload>
          </el-col>
          <el-col :span="8">
            <el-form-item label="提示 (可选)">
              <el-input v-model="hint" type="textarea" :rows="3" placeholder="如: 这是雅加达酒店报价表" />
            </el-form-item>
            <el-button type="primary" @click="uploadAndParse" :loading="uploading" :disabled="!file" style="width:100%">
              开始解析
            </el-button>
          </el-col>
        </el-row>
      </div>

      <div v-if="result" class="bws-card">
        <h3>识别结果 — {{ result.extraction_summary || '手动录入' }}</h3>
        <el-alert v-if="result.warnings?.length" type="warning" :closable="false" style="margin-bottom:12px">
          <template #title>注意事项</template>
          <ul style="margin:6px 0 0;padding-left:18px">
            <li v-for="(w,i) in result.warnings" :key="i">{{ w }}</li>
          </ul>
        </el-alert>
        <p style="color:#6b7280;margin:0 0 12px;font-size:12px">
          可手动修改下表的<strong>类型 / 名称 / 价格 / 备注</strong>,改完点确认入库。
        </p>

        <el-table :data="result.resources" border stripe size="small"
                  @selection-change="(rows) => selectedRows = rows">
          <el-table-column type="selection" width="48" />
          <el-table-column label="类型" width="140">
            <template #default="s">
              <el-select v-model="s.row.resource_type" size="small">
                <el-option v-for="o in typeOptions()" :key="o.v" :label="o.l" :value="o.v" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="信心" width="70">
            <template #default="s">{{ Math.round((s.row.confidence||0)*100) }}%</template>
          </el-table-column>
          <el-table-column label="名称" min-width="220">
            <template #default="s">
              <template v-if="s.row.resource_type === 'hotel_room'">
                <el-input :model-value="getHotelName(s.row)" @update:modelValue="v => setHotelName(s.row, v)"
                          size="small" placeholder="酒店名" style="margin-bottom:4px" />
                <el-input :model-value="getName(s.row)" @update:modelValue="v => setName(s.row, v)"
                          size="small" placeholder="房型(如 Deluxe Room)" />
              </template>
              <el-input v-else :model-value="getName(s.row)" @update:modelValue="v => setName(s.row, v)"
                        size="small" placeholder="名称" />
            </template>
          </el-table-column>
          <el-table-column label="价格 (IDR)" width="160">
            <template #default="s">
              <el-input-number :model-value="getPrice(s.row)" @update:modelValue="v => setPrice(s.row, v)"
                               size="small" :min="0" :step="50000" controls-position="right"
                               style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column label="区域" width="160">
            <template #default="s">
              <el-select v-if="needsArea(s.row.resource_type)"
                         :model-value="getArea(s.row)"
                         @update:modelValue="v => setArea(s.row, v)"
                         size="small" filterable clearable placeholder="选区域">
                <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                  <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
                </el-option-group>
              </el-select>
              <span v-else style="color:#9ca3af;font-size:12px">—</span>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="180">
            <template #default="s">
              <el-input :model-value="getNote(s.row)" @update:modelValue="v => setNote(s.row, v)"
                        size="small" placeholder="备注(可选)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="s">
              <el-button size="small" type="danger" link @click="removeRow(s.$index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top:12px">
          <button type="button" class="btn-day-add" @click="addRow">+ 手动添加一行</button>
        </div>

        <div style="margin-top:16px;text-align:center">
          <el-button type="primary" size="large" @click="confirm" :disabled="!result.resources?.length">
            确认入库 ({{ selectedRows.length || result.resources?.length || 0 }} 条)
          </el-button>
          <el-button @click="result = null">取消</el-button>
        </div>
      </div>
    </div>
  `
};

// ============================================================
//  一日游模板管理
// ============================================================
const TemplateManager = {
  props: ['destinations', 'attractions', 'restaurants'],
  emits: ['refresh'],
  data() {
    return {
      templates: [],
      loading: false,
      keyword: '',
      // 详情对话框
      detailDialog: false,
      detail: null,
      detailLoading: false,
      // 编辑对话框
      editDialog: false,
      editForm: this.makeEmptyForm(),
      saving: false,
      // AI 上传对话框
      uploadDialog: false,
      uploadFile: null,
      uploadHint: '',
      uploadDest: 'DPS',
      uploading: false,
      uploadResult: null,
    };
  },
  computed: {
    filteredTemplates() {
      if (!this.keyword) return this.templates;
      const k = this.keyword.toLowerCase();
      return this.templates.filter(t =>
        (t.name_zh || '').toLowerCase().includes(k) ||
        (t.name_en || '').toLowerCase().includes(k) ||
        (t.description || '').toLowerCase().includes(k));
    },
  },
  methods: {
    makeEmptyForm() {
      return {
        id: null,
        destination_id: null,
        name_zh: '',
        name_en: '',
        description: '',
        total_minutes_estimate: 480,
        recommended_pax_min: 1,
        recommended_pax_max: 17,
        difficulty: 'easy',
        attractions: [],
        restaurants: [],
      };
    },
    async load() {
      this.loading = true;
      try { this.templates = (await http.get('/templates')).data; }
      finally { this.loading = false; }
    },
    destName(id) {
      const d = this.destinations?.find(x => x.id === id);
      return d ? d.name_zh : '?';
    },
    attractionName(id) {
      return this.attractions?.find(a => a.id === id)?.name_zh || `#${id}`;
    },
    restaurantName(id) {
      return this.restaurants?.find(r => r.id === id)?.name_zh || `#${id}`;
    },

    // ---- 详情 ----
    async openDetail(row) {
      this.detailDialog = true;
      this.detailLoading = true;
      try { this.detail = (await http.get(`/templates/${row.id}`)).data; }
      finally { this.detailLoading = false; }
    },

    // ---- 编辑/新增 ----
    openCreate() {
      this.editForm = this.makeEmptyForm();
      this.editForm.destination_id = this.destinations?.[0]?.id || null;
      this.editDialog = true;
    },
    async openEdit(row) {
      const t = (await http.get(`/templates/${row.id}`)).data;
      this.editForm = {
        id: t.id,
        destination_id: t.destination_id,
        name_zh: t.name_zh || '',
        name_en: t.name_en || '',
        description: t.description || '',
        total_minutes_estimate: t.total_minutes_estimate || 480,
        recommended_pax_min: t.recommended_pax_min || 1,
        recommended_pax_max: t.recommended_pax_max || 17,
        difficulty: t.difficulty || 'easy',
        attractions: (t.attractions || []).map(a => ({
          attraction_id: a.attraction_id,
          order_index: a.order_index,
          stay_minutes: a.stay_minutes,
        })),
        restaurants: (t.restaurants || []).map(r => ({
          restaurant_id: r.restaurant_id,
          meal_type: r.meal_type,
        })),
      };
      this.editDialog = true;
    },
    addAttrRow() {
      this.editForm.attractions.push({
        attraction_id: null,
        order_index: this.editForm.attractions.length + 1,
        stay_minutes: 60,
      });
    },
    removeAttrRow(idx) {
      this.editForm.attractions.splice(idx, 1);
      this.editForm.attractions.forEach((a, i) => a.order_index = i + 1);
    },
    moveAttr(idx, dir) {
      const target = idx + dir;
      if (target < 0 || target >= this.editForm.attractions.length) return;
      const tmp = this.editForm.attractions[idx];
      this.editForm.attractions[idx] = this.editForm.attractions[target];
      this.editForm.attractions[target] = tmp;
      this.editForm.attractions.forEach((a, i) => a.order_index = i + 1);
    },
    addRestRow() {
      this.editForm.restaurants.push({ restaurant_id: null, meal_type: 'lunch' });
    },
    removeRestRow(idx) {
      this.editForm.restaurants.splice(idx, 1);
    },
    async saveTemplate() {
      if (!this.editForm.name_zh) { ElementPlus.ElMessage.warning('请填中文名'); return; }
      if (!this.editForm.destination_id) { ElementPlus.ElMessage.warning('请选目的地'); return; }
      // 过滤掉空 id 的行
      const payload = {
        ...this.editForm,
        attractions: this.editForm.attractions.filter(a => a.attraction_id),
        restaurants: this.editForm.restaurants.filter(r => r.restaurant_id),
      };
      this.saving = true;
      try {
        await http.post('/templates', payload);
        ElementPlus.ElMessage.success(payload.id ? '已保存' : '已新增');
        this.editDialog = false;
        await this.load();
        this.$emit('refresh');
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.saving = false;
      }
    },
    async deleteTemplate(row) {
      if (!confirm(`确认删除模板 "${row.name_zh}"?`)) return;
      await http.delete(`/templates/${row.id}`);
      ElementPlus.ElMessage.success('已删除');
      await this.load();
      this.$emit('refresh');
    },

    // ---- AI 上传 ----
    openUpload() {
      this.uploadFile = null;
      this.uploadHint = '';
      this.uploadDest = this.destinations?.[0]?.code || 'DPS';
      this.uploadResult = null;
      this.uploadDialog = true;
    },
    handleUploadChange(file) {
      this.uploadFile = file.raw;
    },
    async parseUpload() {
      if (!this.uploadFile) { ElementPlus.ElMessage.warning('请选择文件'); return; }
      this.uploading = true;
      const fd = new FormData();
      fd.append('file', this.uploadFile);
      if (this.uploadHint) fd.append('hint', this.uploadHint);
      fd.append('destination_code', this.uploadDest);
      try {
        const r = await http.post('/templates/parse-document', fd, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        this.uploadResult = r.data;
        ElementPlus.ElMessage.success('解析完成,可校对后保存');
      } catch (e) {
        ElementPlus.ElMessage.error('解析失败：' + (e.response?.data?.detail || e.message));
      } finally {
        this.uploading = false;
      }
    },
    applyUploadToForm() {
      if (!this.uploadResult) return;
      this.editForm = {
        id: null,
        destination_id: this.uploadResult.destination_id,
        name_zh: this.uploadResult.name_zh || '',
        name_en: this.uploadResult.name_en || '',
        description: this.uploadResult.description || '',
        total_minutes_estimate: this.uploadResult.total_minutes_estimate || 480,
        recommended_pax_min: 1,
        recommended_pax_max: 17,
        difficulty: this.uploadResult.difficulty || 'easy',
        attractions: (this.uploadResult.attractions || []).map((a, i) => ({
          attraction_id: a.attraction_id,
          order_index: a.order_index || i + 1,
          stay_minutes: a.stay_minutes,
        })),
        restaurants: (this.uploadResult.restaurants || []).map(r => ({
          restaurant_id: r.restaurant_id,
          meal_type: r.meal_type,
        })),
      };
      this.uploadDialog = false;
      this.editDialog = true;
    },
  },
  mounted() { this.load(); },
  template: `
    <div>
      <div class="bws-card">
        <h3>🗺 一日游模板管理
          <div style="margin-left:auto;display:flex;gap:8px">
            <el-button size="small" type="primary" plain @click="openUpload">📄 AI 解析文档</el-button>
            <el-button size="small" type="primary" @click="openCreate">+ 手动新增</el-button>
          </div>
        </h3>
        <el-input v-model="keyword" placeholder="搜索名称/描述" style="width:300px;margin-bottom:12px" clearable />
        <el-table :data="filteredTemplates" v-loading="loading" border stripe>
          <el-table-column label="名称" min-width="220">
            <template #default="s">
              <el-button link type="primary" @click="openDetail(s.row)" style="font-weight:600">
                {{ s.row.name_zh }}
              </el-button>
              <span v-if="s.row.name_en" style="color:#9ca3af;font-size:12px;margin-left:8px">{{ s.row.name_en }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目的地" width="110">
            <template #default="s">{{ destName(s.row.destination_id) }}</template>
          </el-table-column>
          <el-table-column label="难度" width="100">
            <template #default="s">
              <el-tag size="small" :type="{easy:'success',moderate:'warning',intense:'danger'}[s.row.difficulty]||'info'">
                {{ {easy:'轻松',moderate:'中等',intense:'强度'}[s.row.difficulty] || s.row.difficulty }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="total_minutes_estimate" label="估时(分钟)" width="110" />
          <el-table-column label="景点 / 餐" width="120">
            <template #default="s">
              {{ s.row.attractions?.length || 0 }} 景点 / {{ s.row.restaurants?.length || 0 }} 餐
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="s">
              <el-button size="small" link @click="openDetail(s.row)">查看</el-button>
              <el-button size="small" link type="primary" @click="openEdit(s.row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="deleteTemplate(s.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 详情 dialog -->
      <el-dialog v-model="detailDialog" :title="'模板详情:' + (detail?.name_zh || '')" width="700px">
        <div v-loading="detailLoading">
          <div v-if="detail">
            <p style="margin:0 0 8px;color:#6b7280">
              <el-tag size="small">{{ detail.destination_name }}</el-tag>
              <el-tag size="small" type="info" style="margin-left:6px">{{ detail.difficulty }}</el-tag>
              <span style="margin-left:8px">⏱ 约 {{ detail.total_minutes_estimate }} 分钟</span>
              <span style="margin-left:8px">👤 {{ detail.recommended_pax_min }}–{{ detail.recommended_pax_max }} 人</span>
            </p>
            <p v-if="detail.name_en" style="color:#9ca3af">{{ detail.name_en }}</p>
            <p v-if="detail.description" style="background:#f9fafb;padding:10px;border-radius:6px">{{ detail.description }}</p>

            <h4 style="margin:14px 0 6px">📍 景点路线 ({{ detail.attractions?.length || 0 }})</h4>
            <div v-if="!detail.attractions?.length" style="color:#9ca3af">(无景点)</div>
            <ol style="padding-left:20px;line-height:1.8">
              <li v-for="(a, i) in detail.attractions" :key="i">
                <strong>{{ a.name_zh }}</strong>
                <span v-if="a.area" style="color:#6b7280">（{{ a.area }}）</span>
                <span v-if="a.stay_minutes" style="color:#9ca3af">· 停留 {{ a.stay_minutes }} 分钟</span>
                <span v-if="a.ticket_idr_adult" style="color:#dc2626">· 成人门票 {{ a.ticket_idr_adult.toLocaleString() }} IDR</span>
              </li>
            </ol>

            <h4 style="margin:14px 0 6px">🍽 用餐 ({{ detail.restaurants?.length || 0 }})</h4>
            <div v-if="!detail.restaurants?.length" style="color:#9ca3af">(无餐厅)</div>
            <ul style="padding-left:20px;line-height:1.8">
              <li v-for="(r, i) in detail.restaurants" :key="i">
                <el-tag size="small" :type="r.meal_type==='lunch'?'warning':'primary'">
                  {{ {lunch:'午',dinner:'晚',both:'午/晚'}[r.meal_type] || r.meal_type }}
                </el-tag>
                <strong style="margin-left:6px">{{ r.name_zh }}</strong>
                <span v-if="r.cost_idr_per_person" style="color:#dc2626;margin-left:8px">{{ r.cost_idr_per_person.toLocaleString() }} IDR/人</span>
              </li>
            </ul>
          </div>
        </div>
        <template #footer>
          <el-button @click="detailDialog = false">关闭</el-button>
          <el-button type="primary" @click="detailDialog = false; openEdit(detail)" v-if="detail">编辑</el-button>
        </template>
      </el-dialog>

      <!-- 编辑/新增 dialog -->
      <el-dialog v-model="editDialog" :title="editForm.id ? '编辑模板' : '新增模板'" width="800px">
        <el-form label-width="100px">
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="目的地" required>
                <el-select v-model="editForm.destination_id" style="width:100%">
                  <el-option v-for="d in destinations" :key="d.id" :label="d.name_zh" :value="d.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="难度">
                <el-radio-group v-model="editForm.difficulty">
                  <el-radio-button value="easy">轻松</el-radio-button>
                  <el-radio-button value="moderate">中等</el-radio-button>
                  <el-radio-button value="intense">强度</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="中文名" required>
                <el-input v-model="editForm.name_zh" placeholder="如:乌布文化一日游" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="英文名">
                <el-input v-model="editForm.name_en" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="描述">
            <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="景点 → 景点 → 午餐 → 景点" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="估时(分)">
                <el-input-number v-model="editForm.total_minutes_estimate" :step="30" :min="60" :max="900" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="最少人数">
                <el-input-number v-model="editForm.recommended_pax_min" :min="1" :max="50" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="最多人数">
                <el-input-number v-model="editForm.recommended_pax_max" :min="1" :max="50" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 景点 -->
          <el-form-item label="景点路线">
            <div v-for="(a, i) in editForm.attractions" :key="i"
                 style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
              <el-tag>#{{ i + 1 }}</el-tag>
              <el-select v-model="a.attraction_id" filterable placeholder="选景点" style="flex:1">
                <el-option v-for="x in attractions" :key="x.id" :label="x.name_zh + (x.area?'('+x.area+')':'')" :value="x.id" />
              </el-select>
              <el-input-number v-model="a.stay_minutes" :step="15" :min="0" :max="600" placeholder="停留分钟" style="width:140px" controls-position="right" />
              <el-button size="small" @click="moveAttr(i, -1)" :disabled="i===0">↑</el-button>
              <el-button size="small" @click="moveAttr(i, 1)" :disabled="i===editForm.attractions.length-1">↓</el-button>
              <el-button size="small" type="danger" link @click="removeAttrRow(i)">删除</el-button>
            </div>
            <el-button size="small" plain @click="addAttrRow">+ 添加景点</el-button>
          </el-form-item>

          <!-- 餐厅 -->
          <el-form-item label="用餐安排">
            <div v-for="(r, i) in editForm.restaurants" :key="i"
                 style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
              <el-select v-model="r.meal_type" style="width:100px">
                <el-option label="午餐" value="lunch" />
                <el-option label="晚餐" value="dinner" />
                <el-option label="午+晚" value="both" />
              </el-select>
              <el-select v-model="r.restaurant_id" filterable placeholder="选餐厅" style="flex:1">
                <el-option v-for="x in restaurants" :key="x.id" :label="x.name_zh" :value="x.id" />
              </el-select>
              <el-button size="small" type="danger" link @click="removeRestRow(i)">删除</el-button>
            </div>
            <el-button size="small" plain @click="addRestRow">+ 添加餐厅</el-button>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDialog = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
        </template>
      </el-dialog>

      <!-- AI 上传 dialog -->
      <el-dialog v-model="uploadDialog" title="AI 解析一日游文档" width="700px">
        <div v-if="!uploadResult">
          <el-form label-width="80px">
            <el-form-item label="目的地">
              <el-select v-model="uploadDest" style="width:200px">
                <el-option v-for="d in destinations" :key="d.code" :label="d.name_zh" :value="d.code" />
              </el-select>
            </el-form-item>
            <el-form-item label="提示">
              <el-input v-model="uploadHint" type="textarea" :rows="2" placeholder="如:这是乌布文化半日游 PPT" />
            </el-form-item>
            <el-form-item label="文件">
              <el-upload drag :auto-upload="false" :on-change="handleUploadChange"
                         :show-file-list="true" :limit="1"
                         accept=".pdf,.docx,.xlsx,.xls">
                <el-icon class="el-icon--upload" style="font-size:36px;color:#1e2761"><upload-filled /></el-icon>
                <div class="el-upload__text">拖拽或<em>点击</em>选择文件</div>
                <template #tip><div class="el-upload__tip">支持 PDF / DOCX / Excel</div></template>
              </el-upload>
            </el-form-item>
          </el-form>
        </div>
        <div v-else>
          <el-alert v-if="uploadResult._mock" title="MOCK 模式 — 配置 ANTHROPIC_API_KEY 走真实解析" type="info" :closable="false" style="margin-bottom:10px" />
          <el-alert v-if="uploadResult.unmatched_attractions?.length" type="warning" :closable="false" style="margin-bottom:10px">
            <template #title>未匹配到景点(将不会入模板,需先去资源库添加)</template>
            <div>{{ uploadResult.unmatched_attractions.join(' / ') }}</div>
          </el-alert>
          <el-alert v-if="uploadResult.unmatched_restaurants?.length" type="warning" :closable="false" style="margin-bottom:10px">
            <template #title>未匹配到餐厅</template>
            <div>{{ uploadResult.unmatched_restaurants.join(' / ') }}</div>
          </el-alert>
          <h4>识别结果</h4>
          <p><strong>名称:</strong> {{ uploadResult.name_zh }}</p>
          <p v-if="uploadResult.description"><strong>描述:</strong> {{ uploadResult.description }}</p>
          <p><strong>估时:</strong> {{ uploadResult.total_minutes_estimate }} 分钟</p>
          <p><strong>景点 ({{ uploadResult.attractions?.length || 0 }}):</strong>
            <span v-for="(a, i) in uploadResult.attractions" :key="i" style="margin-right:8px">
              {{ i + 1 }}.{{ a.name_zh }}
            </span>
          </p>
          <p><strong>餐厅 ({{ uploadResult.restaurants?.length || 0 }}):</strong>
            <span v-for="(r, i) in uploadResult.restaurants" :key="i" style="margin-right:8px">
              {{ {lunch:'午',dinner:'晚',both:'午/晚'}[r.meal_type] }}-{{ r.name_zh }}
            </span>
          </p>
        </div>
        <template #footer>
          <el-button @click="uploadDialog = false">关闭</el-button>
          <el-button v-if="!uploadResult" type="primary" :loading="uploading" :disabled="!uploadFile" @click="parseUpload">开始解析</el-button>
          <el-button v-else type="primary" @click="applyUploadToForm">下一步:校对并保存</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// ============================================================
//  设置面板
// ============================================================
const SettingsPanel = {
  emits: ['rate-changed'],
  data() {
    return {
      rate: { rate_cny_to_idr: 2300, set_by: '' },
      tb: {}, gc: {},
      // v0.5.3: rules/ruleForm/ruleDialog 已退役 (NoGambleRule legacy 卡片删除)
      conditionTypes: [],
      // 区域规则
      areaRules: [],
      areasGrouped: {},
      areaRuleDialog: false,
      areaRuleForm: { hotel_area: '', excluded_attraction_area: '', severity: 'warning', message: '', active: true },
      // 景点互斥规则
      attrConflicts: [],
      attractions: [],
      attrConflictDialog: false,
      attrConflictForm: { attraction_a_id: null, attraction_b_id: null, severity: 'warning', message: '', active: true },
      // ===== v0.3 赌自费策略 =====
      strategies: [],
      strategyDialog: false,
      strategyForm: { name: '', description: '', conditions: [], action: 'skip', gamble_cny: 0, extra_profit_cny: 0, priority: 50, active: true },
      // ===== v0.3 策略预览 (案例编辑器) =====
      previewDialog: false,
      previewForm: {
        customer_type: 'family', season: 'shoulder',
        free_hours_total: 8, total_days: 5, pax_total: 2,
        is_first_time_agency: false, all_meals_included: false,
        has_spa_booked: false, has_water_booked: false,
      },
      previewResult: null,
      // ===== v0.5 策略胜率统计 =====
      strategyStats: { items: [], window_days: 90, total_quotes: 0 },
      strategyStatsLoading: false,
      strategyStatsAccessible: true,
      strategyStatsWindow: 90,
      // ===== v0.7 账号与权限管理 =====
      roleInfo: null,            // /admin/role-info 数据 (权限矩阵)
      allUsers: [],              // 全部用户(super_admin 看全社, owner 看本社)
      allAgencies: [],
      allInvitations: [],
      adminQuotas: [],           // 配额表(可覆盖)
      usageLogs: [],             // 使用日志
      acctTab: 'users',          // 默认 tab
      inviteDialog: false,
      inviteForm: { agency_id: null, role: 'agent', max_uses: 1, expires_in_days: 30, note: '' },
      inviteResult: null,
      acctAccessible: true,      // 仅 super_admin / agency_owner / ops_manager 可见
      myUserRole: '',            // 用户自己的 role (用于决定显示哪些 tab)
      // ===== v0.8 新增 =====
      pendingUsers: [],          // 待审核
      reviewDialog: false,
      reviewTarget: null,        // 当前审核的 user
      reviewForm: { approve: true, role: '', agency_id: null, review_note: '' },
      agencyDialog: false,
      agencyForm: { id: null, name: '', short_name: '', contact_person: '', phone: '', email: '', commission_rate: 0, status: 'active' },
      usageStats: null,          // 7 天聚合
      usageStatsLoading: false,
      // v0.8.3 用户管理操作
      resetPwdDialog: false,
      resetPwdTarget: null,
      resetPwdForm: { new_password: '', force_change: true },
      // v0.8.4 直接创建用户
      createUserDialog: false,
      createUserForm: {
        username: '', password: '', display_name: '',
        email: '', phone: '', role: 'agent', agency_id: null,
      },
    };
  },
  methods: {
    async loadAll() {
      this.rate = (await http.get('/settings/exchange-rate')).data;
      this.tb = (await http.get('/settings/time-budget')).data;
      this.gc = (await http.get('/settings/gamble-config')).data;
      // v0.5.3: NoGambleRule CRUD 已退役; condition-types 端点保留供 GambleStrategy 编辑器使用
      this.conditionTypes = (await http.get('/settings/no-gamble-rules/condition-types')).data;
      this.areaRules = (await http.get('/settings/area-rules')).data;
      this.areasGrouped = (await http.get('/settings/areas')).data.grouped || {};
      this.attrConflicts = (await http.get('/settings/attraction-conflicts')).data || [];
      this.attractions = (await http.get('/resources/attractions')).data || [];
      // v0.3 策略
      this.strategies = (await http.get('/settings/gamble-strategies')).data || [];
      // v0.5 策略胜率
      await this.loadStrategyStats();
      // v0.7 账号与权限
      await this.loadAccountData();
    },
    async loadAccountData() {
      // 拉取自己的角色, 决定能看哪些
      try {
        const me = (await http.get('/auth/me')).data;
        this.myUserRole = me.role;
      } catch (e) {
        this.acctAccessible = false;
        return;
      }
      if (!['super_admin', 'agency_owner', 'ops_manager'].includes(this.myUserRole)) {
        this.acctAccessible = false;
        return;
      }
      this.acctAccessible = true;
      // 拉权限矩阵 (super 才能拉)
      if (this.myUserRole === 'super_admin') {
        try { this.roleInfo = (await http.get('/admin/role-info')).data; } catch (e) {}
        try { this.allAgencies = (await http.get('/agencies')).data || []; } catch (e) {}
      }
      try { this.allUsers = (await http.get('/users')).data || []; } catch (e) {}
      try { this.allInvitations = (await http.get('/invitations')).data || []; } catch (e) {}
      try { this.adminQuotas = (await http.get('/admin/quotas')).data || []; } catch (e) {}
      // v0.8: 待审核 + 全 agencies (供审核 dialog 选)
      try { this.pendingUsers = (await http.get('/admin/pending-users')).data || []; } catch (e) {}
      if (!this.allAgencies.length) {
        try { this.allAgencies = (await http.get('/agencies')).data || []; } catch (e) {}
      }
    },
    openReview(user) {
      this.reviewTarget = user;
      this.reviewForm = {
        approve: true,
        role: user.requested_role,
        agency_id: user.agency_id,
        review_note: '',
      };
      this.reviewDialog = true;
    },
    async submitReview() {
      try {
        await http.post(`/admin/pending-users/${this.reviewTarget.id}/review`, this.reviewForm);
        ElementPlus.ElMessage.success(this.reviewForm.approve ? '✓ 已批准, 用户可以登录' : '✗ 已拒绝');
        this.reviewDialog = false;
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('审核失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    quickReject(user) {
      this.reviewTarget = user;
      this.reviewForm = { approve: false, review_note: '' };
      this.reviewDialog = true;
    },
    openAgency(agency) {
      if (agency) {
        this.agencyForm = JSON.parse(JSON.stringify(agency));
      } else {
        this.agencyForm = { id: null, name: '', short_name: '', contact_person: '', phone: '', email: '', commission_rate: 0, status: 'active' };
      }
      this.agencyDialog = true;
    },
    async saveAgency() {
      if (!this.agencyForm.name) { ElementPlus.ElMessage.warning('旅行社名必填'); return; }
      try {
        await http.post('/agencies', this.agencyForm);
        ElementPlus.ElMessage.success('已保存');
        this.agencyDialog = false;
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    openCreateUser() {
      this.createUserForm = {
        username: '', password: '', display_name: '',
        email: '', phone: '', role: 'agent',
        agency_id: this.myUserRole === 'agency_owner' ? this.currentMyAgencyId : null,
      };
      this.createUserDialog = true;
    },
    async submitCreateUser() {
      const f = this.createUserForm;
      if (!f.username || f.username.length < 4) { ElementPlus.ElMessage.warning('用户名至少 4 字符'); return; }
      if (!f.password || f.password.length < 8) { ElementPlus.ElMessage.warning('密码至少 8 位'); return; }
      if (!f.agency_id && this.myUserRole === 'super_admin') {
        ElementPlus.ElMessage.warning('请选择所属旅行社'); return;
      }
      try {
        const r = await http.post('/users', f);
        ElementPlus.ElMessage.success(`✓ 已创建用户 ${r.data.username}`);
        this.createUserDialog = false;
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('创建失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async unlockUser(user) {
      try {
        await http.post(`/admin/users/${user.id}/unlock`);
        ElementPlus.ElMessage.success(`✓ 已解锁 ${user.username}`);
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('解锁失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    openResetPwd(user) {
      this.resetPwdTarget = user;
      this.resetPwdForm = { new_password: '', force_change: true };
      this.resetPwdDialog = true;
    },
    async submitResetPwd() {
      if (!this.resetPwdForm.new_password || this.resetPwdForm.new_password.length < 6) {
        ElementPlus.ElMessage.warning('新密码至少 6 位');
        return;
      }
      try {
        await http.post(`/admin/users/${this.resetPwdTarget.id}/reset-password`, this.resetPwdForm);
        ElementPlus.ElMessage.success(`✓ 已重置 ${this.resetPwdTarget.username} 的密码`);
        this.resetPwdDialog = false;
      } catch (e) {
        ElementPlus.ElMessage.error('重置失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async disableUser(user) {
      if (!confirm(`确定停用 ${user.username}? 该用户将无法登录.`)) return;
      try {
        await http.post(`/admin/users/${user.id}/disable`);
        ElementPlus.ElMessage.success(`✓ 已停用 ${user.username}`);
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async activateUser(user) {
      try {
        await http.post(`/admin/users/${user.id}/activate`);
        ElementPlus.ElMessage.success(`✓ 已启用 ${user.username}`);
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async loadUsageStats() {
      this.usageStatsLoading = true;
      try {
        const r = await http.get('/admin/usage-stats?days=7');
        this.usageStats = r.data;
      } catch (e) {
        ElementPlus.ElMessage.error('统计拉取失败: ' + (e.response?.data?.detail || e.message));
      } finally {
        this.usageStatsLoading = false;
      }
    },
    async createInvite() {
      try {
        const r = await http.post('/invitations', this.inviteForm);
        this.inviteResult = r.data;
        ElementPlus.ElMessage.success(`邀请码已生成: ${r.data.code}`);
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('生成失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    copyInvite() {
      if (this.inviteResult?.code) {
        navigator.clipboard.writeText(this.inviteResult.code);
        ElementPlus.ElMessage.success('邀请码已复制');
      }
    },
    async resetQuotaUsed(quotaId) {
      try {
        await http.post(`/admin/quotas/${quotaId}/reset`);
        ElementPlus.ElMessage.success('已重置 used = 0');
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('重置失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async overrideQuota(row, newLimit) {
      try {
        await http.post('/admin/quotas/override', {
          user_id: row.user_id, feature: row.feature,
          limit_count: Number(newLimit),
          period: row.period,
          note: '管理员手动调整',
        });
        ElementPlus.ElMessage.success(`已设 ${row.feature_label} 上限 = ${newLimit}`);
        await this.loadAccountData();
      } catch (e) {
        ElementPlus.ElMessage.error('调整失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    async loadUsageLogs() {
      try { this.usageLogs = (await http.get('/admin/usage-logs?days=7&limit=200')).data || []; }
      catch (e) { ElementPlus.ElMessage.error('日志拉取失败: ' + (e.response?.data?.detail || e.message)); }
    },
    roleColor(role) {
      return {
        super_admin: 'danger', ops_manager: 'warning',
        agency_owner: 'success', agent: 'primary', viewer: 'info',
      }[role] || '';
    },
    roleLabelOf(role) {
      return {
        super_admin: '公司超管', ops_manager: '公司 OP', agency_owner: '旅行社老板',
        agent: '业务员', viewer: '只读用户',
      }[role] || role;
    },
    async loadStrategyStats() {
      this.strategyStatsLoading = true;
      try {
        const r = await http.get('/settings/strategy-stats', {
          params: { days: this.strategyStatsWindow },
        });
        this.strategyStats = r.data;
        this.strategyStatsAccessible = true;
      } catch (e) {
        if (e.response?.status === 403) {
          // agent / viewer 看不到 — 静默隐藏
          this.strategyStatsAccessible = false;
          this.strategyStats = { items: [], window_days: this.strategyStatsWindow, total_quotes: 0 };
        }
      } finally {
        this.strategyStatsLoading = false;
      }
    },
    openAttrConflictDialog(rule) {
      if (rule) {
        this.attrConflictForm = JSON.parse(JSON.stringify(rule));
      } else {
        this.attrConflictForm = { attraction_a_id: null, attraction_b_id: null, severity: 'warning', message: '', active: true };
      }
      this.attrConflictDialog = true;
    },
    async saveAttrConflict() {
      if (!this.attrConflictForm.attraction_a_id || !this.attrConflictForm.attraction_b_id) {
        ElementPlus.ElMessage.warning('两个景点都必填'); return;
      }
      if (this.attrConflictForm.attraction_a_id === this.attrConflictForm.attraction_b_id) {
        ElementPlus.ElMessage.warning('两个景点不能相同'); return;
      }
      try {
        await http.post('/settings/attraction-conflicts', this.attrConflictForm);
        this.attrConflictDialog = false;
        ElementPlus.ElMessage.success('已保存');
        this.loadAll();
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败:' + (e.response?.data?.detail || e.message));
      }
    },
    async deleteAttrConflict(id) {
      await http.delete(`/settings/attraction-conflicts/${id}`);
      ElementPlus.ElMessage.success('已删除');
      this.loadAll();
    },
    async toggleAttrConflict(rule) {
      await http.post('/settings/attraction-conflicts', { ...rule });
    },
    openAreaRuleDialog(rule) {
      if (rule) {
        this.areaRuleForm = JSON.parse(JSON.stringify(rule));
      } else {
        this.areaRuleForm = { hotel_area: '', excluded_attraction_area: '', severity: 'warning', message: '', active: true };
      }
      this.areaRuleDialog = true;
    },
    async saveAreaRule() {
      if (!this.areaRuleForm.hotel_area || !this.areaRuleForm.excluded_attraction_area) {
        ElementPlus.ElMessage.warning('住宿区域 + 景点区域都必填');
        return;
      }
      await http.post('/settings/area-rules', this.areaRuleForm);
      this.areaRuleDialog = false;
      ElementPlus.ElMessage.success('规则已保存');
      this.loadAll();
    },
    async deleteAreaRule(id) {
      await http.delete(`/settings/area-rules/${id}`);
      ElementPlus.ElMessage.success('已删除');
      this.loadAll();
    },
    async toggleAreaRule(rule) {
      await http.post('/settings/area-rules', { ...rule });
    },
    // v0.5.3: openRuleDialog/addCondition/removeCondition/saveRule/deleteRule/toggleRule 已删除
    // (NoGambleRule legacy UI 卡片 + 弹窗一并删除, GambleStrategy 编辑器自带条件操作)
    async saveRate() {
      await http.put('/settings/exchange-rate', this.rate);
      ElementPlus.ElMessage.success('汇率已保存');
      this.$emit('rate-changed');
    },
    async saveTb() {
      await http.put('/settings/time-budget', this.tb);
      ElementPlus.ElMessage.success('时间预算已保存');
    },
    async saveGc() {
      await http.put('/settings/gamble-config', this.gc);
      ElementPlus.ElMessage.success('赌自费配置已保存');
    },
    // ===== v0.3 赌自费策略管理 =====
    openStrategyDialog(strategy) {
      if (strategy) {
        this.strategyForm = JSON.parse(JSON.stringify(strategy));
        // 兼容老数据没 extra_profit_cny 字段
        if (this.strategyForm.extra_profit_cny == null) this.strategyForm.extra_profit_cny = 0;
      } else {
        this.strategyForm = {
          name: '', description: '',
          conditions: [{ type: 'free_hours_gt', value: 4 }],
          action: 'fixed', gamble_cny: 200, extra_profit_cny: 0, priority: 50, active: true,
        };
      }
      this.strategyDialog = true;
    },
    cloneStrategy(strategy) {
      const clone = JSON.parse(JSON.stringify(strategy));
      clone.id = null;
      clone.name = strategy.name + ' (副本)';
      clone.priority = Math.max(strategy.priority - 1, 1);
      this.strategyForm = clone;
      this.strategyDialog = true;
    },
    addStrategyCondition() {
      this.strategyForm.conditions.push({ type: 'free_hours_lt', value: 4 });
    },
    removeStrategyCondition(idx) {
      this.strategyForm.conditions.splice(idx, 1);
    },
    async saveStrategy() {
      if (!this.strategyForm.name) { ElementPlus.ElMessage.warning('策略名不能为空'); return; }
      // 类型转换: 数字 / 列表 / 布尔 三种 condition 值规范化
      this.strategyForm.conditions.forEach(c => {
        if (['free_hours_lt','free_hours_gt','total_days_lt','total_days_gt','pax_total_lt','pax_total_gt'].includes(c.type)) {
          c.value = Number(c.value);
        } else if (['customer_type_in','season_in'].includes(c.type)) {
          if (typeof c.value === 'string') c.value = c.value.split(',').map(s=>s.trim()).filter(Boolean);
        } else if (['is_first_time_agency','all_meals_included','spa_already_booked','water_already_booked'].includes(c.type)) {
          c.value = !!c.value;
        }
      });
      // gamble_cny 在 skip 时强制为 0; extra_profit 在赌时强制为 0
      if (this.strategyForm.action === 'skip') {
        this.strategyForm.gamble_cny = 0;
      } else {
        this.strategyForm.extra_profit_cny = 0;
      }
      await http.post('/settings/gamble-strategies', this.strategyForm);
      this.strategyDialog = false;
      ElementPlus.ElMessage.success('策略已保存');
      this.loadAll();
    },
    async deleteStrategy(id) {
      await http.delete(`/settings/gamble-strategies/${id}`);
      ElementPlus.ElMessage.success('已删除');
      this.loadAll();
    },
    async toggleStrategy(strategy) {
      await http.post('/settings/gamble-strategies', { ...strategy });
    },
    // 案例编辑器
    openPreviewDialog() {
      this.previewResult = null;
      this.previewDialog = true;
    },
    async runPreview() {
      const r = await http.post('/settings/gamble-strategies/preview', this.previewForm);
      this.previewResult = r.data;
    },
    async migrateOldRules() {
      try {
        const r = await http.post('/settings/gamble-strategies/migrate-from-no-gamble');
        ElementPlus.ElMessage.success(`迁移完成: ${r.data.migrated} 条新增, ${r.data.skipped_duplicate} 条跳过(已存在)`);
        this.loadAll();
      } catch (e) {
        ElementPlus.ElMessage.error('迁移失败: ' + (e.response?.data?.detail || e.message));
      }
    }
  },
  mounted() { this.loadAll(); },
  template: `
    <div>
      <div class="bws-card">
        <h3>💱 汇率设置</h3>
        <el-form inline>
          <el-form-item label="1 CNY = ">
            <el-input-number v-model="rate.rate_cny_to_idr" :step="10" :min="100" :max="10000" />
            <span style="margin-left:6px">IDR</span>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="rate.note" placeholder="如: 2026Q2 适用" style="width:240px" />
          </el-form-item>
          <el-button type="primary" @click="saveRate">保存</el-button>
        </el-form>
      </div>

      <div class="bws-card">
        <h3>⏱ 时间预算（行程合理性校验用）</h3>
        <el-row :gutter="12">
          <el-col :span="6"><el-form-item label="单日驾驶上限 (分钟)"><el-input-number v-model="tb.max_drive_minutes_per_day" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="预警驾驶 (分钟)"><el-input-number v-model="tb.max_drive_warn_minutes" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="酒店到首站 (分钟)"><el-input-number v-model="tb.hotel_to_first_max_minutes" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="机场缓冲 (分钟)"><el-input-number v-model="tb.airport_buffer_minutes" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="6"><el-form-item label="早高峰系数"><el-input-number v-model="tb.morning_peak_coef" :step="0.05" :precision="2" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="晚高峰系数"><el-input-number v-model="tb.evening_peak_coef" :step="0.05" :precision="2" /></el-form-item></el-col>
          <el-col :span="6"><el-form-item label="节假日系数"><el-input-number v-model="tb.holiday_coef" :step="0.05" :precision="2" /></el-form-item></el-col>
        </el-row>
        <el-button type="primary" @click="saveTb">保存</el-button>
      </div>

      <div class="bws-card">
        <h3>🎲 赌自费总开关</h3>
        <p style="color:#6b7280;margin:0 0 12px;font-size:13px">
          全局开关。关闭后所有报价都不赌(price = 成本 + 利润)。
          具体"哪种行程赌多少 / 哪种不赌"在下方<strong>"赌自费策略"</strong>逐条配置。
        </p>
        <el-form-item label="启用赌自费">
          <el-switch v-model="gc.enable_gambling" active-text="开启 (走策略)" inactive-text="关闭 (全部不赌)" />
          <el-button type="primary" size="small" style="margin-left:16px" @click="saveGc">保存</el-button>
        </el-form-item>
      </div>

      <!-- ===== v0.5 策略胜率统计 ===== -->
      <div class="bws-card" v-if="strategyStatsAccessible">
        <h3>📈 策略胜率统计
          <span style="margin-left:auto;display:flex;gap:8px;align-items:center">
            <el-select v-model="strategyStatsWindow" size="small" style="width:120px" @change="loadStrategyStats">
              <el-option :value="30" label="近 30 天" />
              <el-option :value="60" label="近 60 天" />
              <el-option :value="90" label="近 90 天" />
              <el-option :value="180" label="近 180 天" />
              <el-option :value="365" label="近 1 年" />
            </el-select>
            <el-button size="small" plain :loading="strategyStatsLoading" @click="loadStrategyStats">刷新</el-button>
          </span>
        </h3>
        <p style="color:#6b7280;margin:0 0 12px;font-size:13px">
          基于"团结束反馈"数据反哺策略库 ·
          统计窗口内共 {{ strategyStats.total_quotes }} 单 ·
          胜率 < 60% 持续 10 单建议调整该策略
        </p>
        <el-empty v-if="!strategyStats.items.length" description="暂无策略命中数据,出几单后再来看" />
        <el-table v-else :data="strategyStats.items" border stripe size="small">
          <el-table-column prop="strategy_name" label="策略" min-width="220">
            <template #default="s">
              <span :style="{color: s.row.strategy_id === null ? '#909399' : '#303133'}">
                {{ s.row.strategy_name }}
              </span>
              <el-tag v-if="s.row.action" size="small" style="margin-left:6px"
                :type="s.row.action === 'skip' ? 'info' : 'warning'">
                {{ s.row.action === 'skip' ? '不赌' : '赌·让利' }}
              </el-tag>
              <el-tag v-if="s.row.active === false" size="small" type="danger" style="margin-left:6px">已停用</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="hit_count" label="命中数" width="80" align="right" sortable />
          <el-table-column prop="feedback_count" label="已反馈" width="80" align="right" />
          <el-table-column label="赢/部分/输" width="120" align="center">
            <template #default="s">
              <span style="color:#67c23a">{{ s.row.won_count }}</span>
              <span> / </span>
              <span style="color:#e6a23c">{{ s.row.partial_count }}</span>
              <span> / </span>
              <span style="color:#f56c6c">{{ s.row.lost_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="胜率" width="100" align="right">
            <template #default="s">
              <el-tag v-if="s.row.win_rate === null" size="small" type="info">无数据</el-tag>
              <el-tag v-else size="small"
                :type="s.row.win_rate >= 0.7 ? 'success' : (s.row.win_rate >= 0.6 ? 'warning' : 'danger')">
                {{ (s.row.win_rate * 100).toFixed(1) }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="平均推荐让利" width="120" align="right">
            <template #default="s">¥ {{ s.row.avg_recommended_cny.toFixed(0) }}</template>
          </el-table-column>
          <el-table-column label="平均实际利润" width="120" align="right">
            <template #default="s">
              <span v-if="s.row.avg_actual_profit_cny === null" style="color:#c0c4cc">—</span>
              <span v-else>¥ {{ s.row.avg_actual_profit_cny.toFixed(0) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- ===== v0.5.1 赌自费策略管理 (简化版) ===== -->
      <div class="bws-card">
        <h3>💰 赌自费策略
          <span style="margin-left:auto;display:flex;gap:8px">
            <el-button size="small" type="primary" @click="openPreviewDialog">🔍 案例编辑器/预览</el-button>
            <el-button size="small" type="primary" plain @click="openStrategyDialog(null)">+ 新增策略</el-button>
          </span>
        </h3>
        <el-alert type="success" :closable="false" style="margin-bottom:12px">
          <template #title>怎么用?</template>
          <div style="font-size:13px;line-height:1.7">
            每条策略 = "<strong>什么样的行程</strong>" + "<strong>怎么处理</strong>"。<br>
            <strong>「不赌」</strong>:不让利;甚至可以反向<strong>加 ¥X/人 利润</strong>(适合不会买自费的客群,如 老年/MICE/婚礼/全程含餐 等)<br>
            <strong>「赌」</strong>:主动让 <strong>¥X/人</strong> 出去,博客户买自费补回来(适合 蜜月/年轻人/自由时间多 等)<br>
            按"优先级"从高到低评估,<strong>第一条匹配上就用它,后面不再判断</strong>。所有条件必须同时满足。
          </div>
        </el-alert>
        <el-table :data="strategies" border stripe size="small">
          <el-table-column prop="priority" label="优先级" width="80" sortable />
          <el-table-column prop="name" label="策略名" min-width="220" />
          <el-table-column label="处理方式" width="180">
            <template #default="s">
              <el-tag v-if="s.row.action==='skip' && (s.row.extra_profit_cny || 0) > 0" type="success">
                不赌 + 加 ¥{{ s.row.extra_profit_cny }}/人 利润
              </el-tag>
              <el-tag v-else-if="s.row.action==='skip'" type="info">不赌 (按原价)</el-tag>
              <el-tag v-else-if="s.row.action==='fixed'" type="warning">赌 → 让 ¥{{ s.row.gamble_cny }}/人</el-tag>
              <el-tag v-else-if="s.row.action==='per_pax'" type="warning">赌 → 让 ¥{{ s.row.gamble_cny }}/团 (老格式)</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="触发条件 (全部满足)" min-width="320">
            <template #default="s">
              <el-tag v-for="(c,i) in s.row.conditions" :key="i" size="small" style="margin:2px">
                {{ (conditionTypes.find(t => t.type === c.type) || {label: c.type}).label }}:
                {{ Array.isArray(c.value) ? c.value.join(',') : c.value }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="s">
              <el-switch v-model="s.row.active" @change="toggleStrategy(s.row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="s">
              <el-button size="small" link @click="openStrategyDialog(s.row)">编辑</el-button>
              <el-button size="small" link @click="cloneStrategy(s.row)">复制</el-button>
              <el-button size="small" type="danger" link @click="deleteStrategy(s.row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- ===== 策略编辑弹窗 (v0.5.1 简化) ===== -->
      <el-dialog v-model="strategyDialog" title="编辑赌自费策略" width="780px">
        <el-form label-width="120px">
          <el-form-item label="策略名 ★">
            <el-input v-model="strategyForm.name" placeholder="如: 蜜月+自由时间多+旺季 → 让 ¥450/人" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="strategyForm.description" type="textarea" :rows="2"
              placeholder="可选: 这条策略针对什么场景, 为什么这样设" />
          </el-form-item>

          <el-form-item label="处理方式 ★">
            <el-radio-group v-model="strategyForm.action" size="large">
              <el-radio-button value="skip">🛡 不赌</el-radio-button>
              <el-radio-button value="fixed">🎲 赌 (让利 ¥/人)</el-radio-button>
            </el-radio-group>
            <div style="color:#909399;font-size:12px;margin-top:6px">
              <span v-if="strategyForm.action==='skip'">
                <strong>不赌</strong>: 报价正常算, 不让利;还可以选择反向加利润
              </span>
              <span v-else>
                <strong>赌</strong>: 给客户让 ¥X/人 价, 博客户在地玩自费 (SPA/水上/包车...) 把利润赚回来
              </span>
            </div>
          </el-form-item>

          <el-form-item v-if="strategyForm.action==='skip'" label="额外加利润 ¥/人">
            <el-input-number v-model="strategyForm.extra_profit_cny" :min="0" :step="50" :precision="0" style="width:200px" />
            <span style="margin-left:8px;color:#6b7280;font-size:13px">
              0 = 报价不变 · 大于 0 = 反向加价 (适合"反正不会买自费, 多赚一点")
            </span>
          </el-form-item>

          <el-form-item v-else label="让利金额 ¥/人 ★">
            <el-input-number v-model="strategyForm.gamble_cny" :min="0" :step="50" :precision="0" style="width:200px" />
            <span style="margin-left:8px;color:#6b7280;font-size:13px">
              报价里减掉这个金额, 期望客户在地玩自费补回利润
            </span>
          </el-form-item>

          <el-form-item label="优先级">
            <el-input-number v-model="strategyForm.priority" :min="0" :max="999" style="width:120px" />
            <span style="margin-left:8px;color:#6b7280;font-size:13px">数大先评估 (建议: 越具体的策略给越高优先级)</span>
          </el-form-item>
          <el-form-item label="启用"><el-switch v-model="strategyForm.active" /></el-form-item>

          <el-divider>触发条件 (必须全部满足才会命中)</el-divider>
          <el-form-item label="">
            <div style="width:100%">
              <div v-for="(c, i) in strategyForm.conditions" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
                <el-select v-model="c.type" style="width:240px" placeholder="选条件类型">
                  <el-option v-for="ct in conditionTypes" :key="ct.type" :label="ct.label" :value="ct.type" />
                </el-select>
                <el-input v-model="c.value" placeholder="值; 列表用逗号分隔" style="flex:1" />
                <el-button size="small" type="danger" link @click="removeStrategyCondition(i)">删除</el-button>
              </div>
              <el-button size="small" plain @click="addStrategyCondition">+ 添加条件</el-button>
              <span style="color:#909399;font-size:12px;margin-left:12px">
                条件示例: 蜜月 = customer_type_in: honeymoon · 自由时间多 = free_hours_gt: 8 · 含SPA = spa_already_booked: true
              </span>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="strategyDialog = false">取消</el-button>
          <el-button type="primary" @click="saveStrategy">保存</el-button>
        </template>
      </el-dialog>

      <!-- ===== v0.3 案例编辑器/预览 弹窗 ===== -->
      <el-dialog v-model="previewDialog" title="🔍 案例编辑器 — 模拟一份行程, 看哪条策略命中" width="820px">
        <el-form inline label-width="80px">
          <el-row :gutter="12">
            <el-col :span="8"><el-form-item label="客户类型">
              <el-select v-model="previewForm.customer_type" style="width:140px">
                <el-option label="蜜月" value="honeymoon" />
                <el-option label="婚礼" value="wedding" />
                <el-option label="亲子" value="family_kids" />
                <el-option label="年轻人" value="young" />
                <el-option label="家庭" value="family" />
                <el-option label="老年" value="senior" />
                <el-option label="MICE" value="mice" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="8"><el-form-item label="季节">
              <el-select v-model="previewForm.season" style="width:120px">
                <el-option label="淡季" value="low" />
                <el-option label="平季" value="shoulder" />
                <el-option label="旺季" value="high" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="8"><el-form-item label="天数"><el-input-number v-model="previewForm.total_days" :min="1" :max="30" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="自由(h)"><el-input-number v-model="previewForm.free_hours_total" :min="0" :max="200" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="人数"><el-input-number v-model="previewForm.pax_total" :min="1" :max="100" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="新客户"><el-switch v-model="previewForm.is_first_time_agency" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="全含餐"><el-switch v-model="previewForm.all_meals_included" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="含SPA"><el-switch v-model="previewForm.has_spa_booked" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="含水上"><el-switch v-model="previewForm.has_water_booked" /></el-form-item></el-col>
          </el-row>
        </el-form>
        <div style="margin-top:8px"><el-button type="primary" @click="runPreview">🚀 评估</el-button></div>
        <div v-if="previewResult" style="margin-top:16px">
          <el-alert :type="previewResult.matched ? 'success' : 'warning'" :closable="false">
            <template #title><strong>{{ previewResult.result_text }}</strong></template>
          </el-alert>
          <div style="margin-top:12px"><strong>评估轨迹 (按优先级顺序):</strong></div>
          <el-table :data="previewResult.trace" size="small" border style="margin-top:6px">
            <el-table-column prop="priority" label="优先" width="60" />
            <el-table-column prop="name" label="策略名" min-width="200" />
            <el-table-column label="动作" width="140">
              <template #default="s">
                {{ s.row.action === 'skip' ? '不赌'
                   : s.row.action === 'fixed' ? '¥' + s.row.gamble_cny + '/人'
                   : '¥' + s.row.gamble_cny + '/团' }}
              </template>
            </el-table-column>
            <el-table-column label="结果" width="120">
              <template #default="s">
                <el-tag v-if="s.row.evaluated === false" type="info">未评估</el-tag>
                <el-tag v-else-if="s.row.matched" type="success">✓ 命中</el-tag>
                <el-tag v-else type="info">✗ 未命中</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="条件检查" min-width="300">
              <template #default="s">
                <el-tag v-for="(cr,i) in (s.row.conditions || [])" :key="i" size="small"
                        :type="cr.passed ? 'success' : 'danger'" style="margin:2px">
                  {{ cr.passed ? '✓' : '✗' }} {{ cr.condition.type }}: {{ Array.isArray(cr.condition.value) ? cr.condition.value.join(',') : cr.condition.value }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <template #footer>
          <el-button @click="previewDialog = false">关闭</el-button>
        </template>
      </el-dialog>

      <!-- v0.5.3: 不赌自费规则 (legacy NoGambleRule) 卡片已删除, 由"💰 赌自费策略"完全替代 -->

      <!-- 区域不兼容规则 -->
      <div class="bws-card">
        <h3>🗺 区域不兼容规则(防止极限/不合理行程)
          <el-button size="small" type="primary" plain @click="openAreaRuleDialog(null)" style="margin-left:auto">新增规则</el-button>
        </h3>
        <p style="color:#6b7280;margin:0 0 12px;font-size:13px">
          住宿区域 + 同日景点区域不合理时,行程合理性校验会按严重度警告或拦截。
          例:住努沙杜瓦不能去罗威纳(单程 4h),住乌布去乌鲁瓦图日落需傍晚返程紧张。
        </p>
        <el-table :data="areaRules" border stripe size="small">
          <el-table-column prop="hotel_area" label="住宿区域" width="160" />
          <el-table-column prop="excluded_attraction_area" label="排除景点区域" width="160" />
          <el-table-column label="严重度" width="100">
            <template #default="s">
              <el-tag :type="s.row.severity === 'error' ? 'danger' : 'warning'" size="small">
                {{ s.row.severity === 'error' ? '错误(拦截)' : '警告' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="提示语" />
          <el-table-column label="启用" width="80">
            <template #default="s">
              <el-switch v-model="s.row.active" @change="toggleAreaRule(s.row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link @click="openAreaRuleDialog(s.row)">编辑</el-button>
              <el-button size="small" type="danger" link @click="deleteAreaRule(s.row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 景点互斥规则 -->
      <div class="bws-card">
        <h3>🚫 景点互斥规则(同一天不能并存)
          <el-button size="small" type="primary" plain @click="openAttrConflictDialog(null)" style="margin-left:auto">新增规则</el-button>
        </h3>
        <p style="color:#6b7280;margin:0 0 12px;font-size:13px">
          两个景点同日时按严重度警告/拦截。例:罗威纳海豚(凌晨 5:00 出发)与乌鲁瓦图日落 → 时间不可行;两个梯田 → 同区域重复。
        </p>
        <el-table :data="attrConflicts" border stripe size="small">
          <el-table-column prop="attraction_a_name" label="景点 A" min-width="180" />
          <el-table-column prop="attraction_b_name" label="景点 B" min-width="180" />
          <el-table-column label="严重度" width="100">
            <template #default="s">
              <el-tag :type="s.row.severity === 'error' ? 'danger' : 'warning'" size="small">
                {{ s.row.severity === 'error' ? '错误(拦截)' : '警告' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="提示语" />
          <el-table-column label="启用" width="80">
            <template #default="s">
              <el-switch v-model="s.row.active" @change="toggleAttrConflict(s.row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="s">
              <el-button size="small" link @click="openAttrConflictDialog(s.row)">编辑</el-button>
              <el-button size="small" type="danger" link @click="deleteAttrConflict(s.row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 编辑/新增景点互斥规则弹窗 -->
      <el-dialog v-model="attrConflictDialog" title="景点互斥规则" width="600px">
        <el-form label-width="120px">
          <el-form-item label="景点 A" required>
            <el-select v-model="attrConflictForm.attraction_a_id" filterable style="width:100%">
              <el-option v-for="a in attractions" :key="a.id"
                         :label="a.name_zh + (a.area ? ' (' + a.area + ')' : '')" :value="a.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="景点 B" required>
            <el-select v-model="attrConflictForm.attraction_b_id" filterable style="width:100%">
              <el-option v-for="a in attractions" :key="a.id"
                         :label="a.name_zh + (a.area ? ' (' + a.area + ')' : '')" :value="a.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="严重度">
            <el-radio-group v-model="attrConflictForm.severity">
              <el-radio value="warning">警告(允许但提示)</el-radio>
              <el-radio value="error">错误(拦截不可行)</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="提示语">
            <el-input v-model="attrConflictForm.message" type="textarea" :rows="2" placeholder="如:海豚 5:00 出发 + 乌鲁瓦图日落 → 时间不可能" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="attrConflictForm.active" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="attrConflictDialog = false">取消</el-button>
          <el-button type="primary" @click="saveAttrConflict">保存</el-button>
        </template>
      </el-dialog>

      <!-- 编辑/新增区域规则弹窗 -->
      <el-dialog v-model="areaRuleDialog" title="编辑区域不兼容规则" width="600px">
        <el-form label-width="120px">
          <el-form-item label="住宿区域" required>
            <el-select v-model="areaRuleForm.hotel_area" filterable style="width:100%">
              <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="排除景点区域" required>
            <el-select v-model="areaRuleForm.excluded_attraction_area" filterable style="width:100%">
              <el-option-group v-for="(areas, group) in areasGrouped" :key="group" :label="group">
                <el-option v-for="a in areas" :key="a" :label="a" :value="a" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="严重度">
            <el-radio-group v-model="areaRuleForm.severity">
              <el-radio value="warning">警告(允许但提示)</el-radio>
              <el-radio value="error">错误(拦截不可行)</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="提示语">
            <el-input v-model="areaRuleForm.message" type="textarea" :rows="2" placeholder="如: 单程 4 小时,当日往返不可行" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="areaRuleForm.active" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="areaRuleDialog = false">取消</el-button>
          <el-button type="primary" @click="saveAreaRule">保存</el-button>
        </template>
      </el-dialog>

      <!-- v0.5.3: ruleDialog (编辑不赌自费规则弹窗) 已删除, GambleStrategy 编辑器已内含完整条件编辑能力 -->

      <!-- ====== v0.7 账号与权限管理 ====== -->
      <div class="bws-card" v-if="acctAccessible" style="border:2px solid #5b21b6">
        <h3>👥 账号与权限管理 <el-tag type="warning" size="small" style="margin-left:8px">v0.7 新</el-tag>
          <span style="margin-left:auto;font-size:12px;color:#909399">
            当前角色: <strong>{{ roleLabelOf(myUserRole) }}</strong>
          </span>
        </h3>
        <el-tabs v-model="acctTab" type="border-card">
          <!-- ===== Tab: 待审核 (顶部, 醒目) ===== -->
          <el-tab-pane name="pending">
            <template #label>
              <span>📋 待审核
                <el-badge v-if="pendingUsers.length > 0" :value="pendingUsers.length" type="danger" />
              </span>
            </template>
            <p style="color:#909399;font-size:13px">自助注册申请, 需要您审批通过后用户才能登录.</p>
            <el-empty v-if="!pendingUsers.length" description="暂无待审核申请" />
            <el-table v-else :data="pendingUsers" size="small" border stripe max-height="400">
              <el-table-column prop="id" label="ID" width="50" />
              <el-table-column prop="username" label="用户名" width="120" />
              <el-table-column prop="display_name" label="显示名" width="120" />
              <el-table-column label="申请角色" width="120">
                <template #default="s">
                  <el-tag :type="roleColor(s.row.requested_role)" size="small">{{ roleLabelOf(s.row.requested_role) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="申请加入" min-width="180">
                <template #default="s">
                  <span v-if="s.row.agency_name">已有: <strong>{{ s.row.agency_name }}</strong></span>
                  <span v-else-if="s.row.requested_agency_name" style="color:#e6a23c">
                    🆕 申请新建: <strong>{{ s.row.requested_agency_name }}</strong>
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="email" label="邮箱" width="160" />
              <el-table-column prop="phone" label="手机" width="120" />
              <el-table-column label="申请理由" min-width="180">
                <template #default="s">
                  <span style="font-size:12px;color:#606266">{{ s.row.application_note || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="申请时间" width="120">
                <template #default="s">
                  <span style="font-size:12px">{{ s.row.created_at?.slice(0, 16).replace('T', ' ') }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="180">
                <template #default="s">
                  <el-button size="small" type="success" @click="openReview(s.row)">审核</el-button>
                  <el-button size="small" type="danger" link @click="quickReject(s.row)">快速拒绝</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab 1: 用户列表 ===== -->
          <el-tab-pane label="👤 用户" name="users">
            <div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">
              <span style="color:#909399;font-size:13px">
                {{ ['super_admin','ops_manager'].includes(myUserRole) ? '全部用户' : '本社用户' }} · 共 {{ allUsers.length }} 人
              </span>
              <span style="display:flex;gap:8px">
                <el-button size="small" type="success" @click="openCreateUser">+ 直接添加用户</el-button>
                <el-button size="small" type="primary" @click="inviteDialog = true">+ 生成邀请码</el-button>
              </span>
            </div>
            <el-table :data="allUsers" size="small" border stripe max-height="380">
              <el-table-column prop="id" label="ID" width="50" />
              <el-table-column prop="username" label="用户名" width="120" />
              <el-table-column prop="display_name" label="显示名" width="120" />
              <el-table-column label="角色" width="120">
                <template #default="s">
                  <el-tag :type="roleColor(s.row.role)" size="small">{{ roleLabelOf(s.row.role) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="agency_name" label="所属旅行社" width="160" />
              <el-table-column prop="status" label="状态" width="80">
                <template #default="s">
                  <el-tag :type="s.row.status==='active' ? 'success' : 'danger'" size="small">{{ s.row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_login_at" label="最后登录" width="160">
                <template #default="s">
                  <span style="font-size:12px">{{ s.row.last_login_at ? s.row.last_login_at.slice(0, 16).replace('T', ' ') : '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="220" fixed="right">
                <template #default="s">
                  <el-button size="small" type="warning" link @click="unlockUser(s.row)">🔓 解锁</el-button>
                  <el-button size="small" type="primary" link @click="openResetPwd(s.row)">🔑 改密</el-button>
                  <el-button v-if="s.row.status==='active'" size="small" type="danger" link @click="disableUser(s.row)">停用</el-button>
                  <el-button v-else size="small" type="success" link @click="activateUser(s.row)">启用</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab 2: 配额管理 ===== -->
          <el-tab-pane label="📊 配额" name="quotas">
            <div style="margin-bottom:8px;color:#909399;font-size:13px">
              共 {{ adminQuotas.length }} 条配额. 双击"上限"列编辑, 或点"重置 used".
            </div>
            <el-table :data="adminQuotas" size="small" border stripe max-height="400">
              <el-table-column prop="user_id" label="用户ID" width="70" />
              <el-table-column prop="feature_label" label="功能" min-width="180" />
              <el-table-column label="周期" width="80">
                <template #default="s">
                  {{ {daily:'每日', monthly:'每月', total:'累计'}[s.row.period] || s.row.period }}
                </template>
              </el-table-column>
              <el-table-column label="已用" width="70" align="right">
                <template #default="s">{{ s.row.used }}</template>
              </el-table-column>
              <el-table-column label="上限" width="100" align="right">
                <template #default="s">
                  <el-input-number :model-value="s.row.limit" size="small" :min="-1"
                    @change="(v) => overrideQuota(s.row, v)" controls-position="right" style="width:90px" />
                </template>
              </el-table-column>
              <el-table-column label="剩余" width="70" align="right">
                <template #default="s">
                  <span v-if="s.row.limit === -1" style="color:#67c23a">∞</span>
                  <span v-else-if="s.row.remaining === 0" style="color:#f56c6c">0</span>
                  <span v-else>{{ s.row.remaining }}</span>
                </template>
              </el-table-column>
              <el-table-column label="覆盖" width="60">
                <template #default="s">
                  <el-tag v-if="s.row.overridden" type="warning" size="small">是</el-tag>
                  <span v-else style="color:#909399">默认</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="s">
                  <el-button size="small" type="warning" link @click="resetQuotaUsed(s.row.id)">重置 used</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab 3: 邀请码 ===== -->
          <el-tab-pane label="📨 邀请码" name="invites">
            <el-table :data="allInvitations" size="small" border stripe max-height="380">
              <el-table-column prop="code" label="邀请码" width="200" />
              <el-table-column label="角色" width="120">
                <template #default="s">
                  <el-tag :type="roleColor(s.row.role)" size="small">{{ roleLabelOf(s.row.role) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="agency_name" label="旅行社" width="160" />
              <el-table-column label="使用" width="100">
                <template #default="s">{{ s.row.used_count }} / {{ s.row.max_uses }}</template>
              </el-table-column>
              <el-table-column prop="expires_at" label="过期" width="160">
                <template #default="s">
                  <span style="font-size:12px">{{ s.row.expires_at ? s.row.expires_at.slice(0, 16).replace('T', ' ') : '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="note" label="备注" />
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab 4: 使用日志 ===== -->
          <el-tab-pane label="📜 使用日志" name="logs">
            <div style="margin-bottom:8px">
              <el-button size="small" @click="loadUsageLogs">刷新近 7 天</el-button>
              <span style="margin-left:12px;color:#909399;font-size:13px">共 {{ usageLogs.length }} 条</span>
            </div>
            <el-table :data="usageLogs" size="small" border stripe max-height="400">
              <el-table-column prop="user_id" label="用户ID" width="70" />
              <el-table-column prop="feature" label="功能" width="200" />
              <el-table-column label="结果" width="60">
                <template #default="s">
                  <el-tag :type="s.row.success ? 'success' : 'danger'" size="small">
                    {{ s.row.success ? '成功' : '失败' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="error_msg" label="错误信息" min-width="200" />
              <el-table-column prop="meta_json" label="元数据" min-width="200">
                <template #default="s">
                  <span style="font-size:11px;color:#606266">{{ s.row.meta_json }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="used_at" label="时间" width="160">
                <template #default="s">
                  <span style="font-size:12px">{{ s.row.used_at.slice(0, 19).replace('T', ' ') }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab: 旅行社管理 (super_admin only) ===== -->
          <el-tab-pane v-if="myUserRole === 'super_admin'" label="🏢 旅行社" name="agencies">
            <div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">
              <span style="color:#909399;font-size:13px">共 {{ allAgencies.length }} 家</span>
              <el-button size="small" type="primary" @click="openAgency(null)">+ 新建旅行社</el-button>
            </div>
            <el-table :data="allAgencies" size="small" border stripe max-height="400">
              <el-table-column prop="id" label="ID" width="50" />
              <el-table-column prop="name" label="名称" min-width="160" />
              <el-table-column prop="short_name" label="简称" width="100" />
              <el-table-column prop="contact_person" label="联系人" width="100" />
              <el-table-column prop="phone" label="电话" width="120" />
              <el-table-column prop="email" label="邮箱" width="160" />
              <el-table-column label="佣金率" width="80">
                <template #default="s">{{ (s.row.commission_rate*100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="s">
                  <el-tag :type="s.row.status==='active' ? 'success' : 'danger'" size="small">{{ s.row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="s">
                  <el-button size="small" link @click="openAgency(s.row)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- ===== Tab: 7 天聚合统计 ===== -->
          <el-tab-pane label="📊 7天统计" name="stats">
            <div style="margin-bottom:12px">
              <el-button size="small" type="primary" @click="loadUsageStats" :loading="usageStatsLoading">刷新统计</el-button>
              <span v-if="usageStats" style="margin-left:12px;color:#909399;font-size:13px">
                近 7 天共 <strong>{{ usageStats.total_calls }}</strong> 次调用,
                成功 <strong style="color:#67c23a">{{ usageStats.total_success }}</strong>,
                失败 <strong style="color:#f56c6c">{{ usageStats.total_failed }}</strong>,
                成功率 {{ (usageStats.success_rate * 100).toFixed(1) }}%
              </span>
            </div>
            <div v-if="!usageStats" style="text-align:center;color:#909399;padding:30px">
              点击 "刷新统计" 加载数据
            </div>
            <el-row v-else :gutter="16">
              <el-col :span="12">
                <h4 style="margin:0 0 8px">📈 按功能 TOP 调用</h4>
                <el-table :data="usageStats.by_feature" size="small" border stripe max-height="350">
                  <el-table-column prop="label" label="功能" min-width="160" />
                  <el-table-column label="总数" width="70" align="right">
                    <template #default="s">
                      <strong>{{ s.row.total }}</strong>
                    </template>
                  </el-table-column>
                  <el-table-column label="成功率" width="180">
                    <template #default="s">
                      <el-progress :percentage="Math.round(s.row.success_rate*100)"
                        :color="s.row.success_rate >= 0.9 ? '#67c23a' : (s.row.success_rate >= 0.7 ? '#e6a23c' : '#f56c6c')" />
                    </template>
                  </el-table-column>
                </el-table>
              </el-col>
              <el-col :span="12">
                <h4 style="margin:0 0 8px">👤 用户调用 TOP 20</h4>
                <el-table :data="usageStats.by_user" size="small" border stripe max-height="350">
                  <el-table-column prop="username" label="用户" min-width="120" />
                  <el-table-column label="角色" width="100">
                    <template #default="s">
                      <el-tag v-if="s.row.role" :type="roleColor(s.row.role)" size="small">{{ roleLabelOf(s.row.role) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="次数" width="100" align="right">
                    <template #default="s"><strong>{{ s.row.total }}</strong></template>
                  </el-table-column>
                  <el-table-column label="占比" width="180">
                    <template #default="s">
                      <el-progress :percentage="Math.round(s.row.total / usageStats.total_calls * 100)" />
                    </template>
                  </el-table-column>
                </el-table>
              </el-col>
            </el-row>
          </el-tab-pane>

          <!-- ===== Tab 5: 权限矩阵 (super_admin only) ===== -->
          <el-tab-pane v-if="myUserRole === 'super_admin' && roleInfo" label="🛡 权限矩阵" name="permissions">
            <p style="color:#909399;font-size:13px">系统硬约束. 修改这些需要改 backend/utils/feature_permissions.py</p>
            <el-table :data="roleInfo.features" size="small" border stripe max-height="500">
              <el-table-column prop="category" label="类别" width="80" />
              <el-table-column prop="label" label="功能" min-width="180" />
              <el-table-column label="允许的角色">
                <template #default="s">
                  <el-tag v-for="r in s.row.allowed_roles" :key="r" :type="roleColor(r)" size="small" style="margin:2px">
                    {{ roleLabelOf(r) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 邀请码生成 dialog -->
      <el-dialog v-model="inviteDialog" title="📨 生成邀请码" width="520px">
        <el-form :model="inviteForm" label-width="120px">
          <el-form-item label="所属旅行社" v-if="myUserRole === 'super_admin'">
            <el-select v-model="inviteForm.agency_id" filterable style="width:100%" placeholder="选择旅行社">
              <el-option v-for="a in allAgencies" :key="a.id" :label="a.name" :value="a.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="inviteForm.role" style="width:200px">
              <el-option v-if="myUserRole === 'super_admin'" label="公司超管 super_admin" value="super_admin" />
              <el-option v-if="myUserRole === 'super_admin'" label="公司 OP ops_manager" value="ops_manager" />
              <el-option v-if="myUserRole === 'super_admin'" label="旅行社老板 agency_owner" value="agency_owner" />
              <el-option label="业务员 agent" value="agent" />
              <el-option label="只读用户 viewer" value="viewer" />
            </el-select>
          </el-form-item>
          <el-form-item label="可用次数">
            <el-input-number v-model="inviteForm.max_uses" :min="1" :max="100" />
          </el-form-item>
          <el-form-item label="有效期(天)">
            <el-input-number v-model="inviteForm.expires_in_days" :min="1" :max="365" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="inviteForm.note" placeholder="如: 给王经理用" />
          </el-form-item>
          <el-form-item v-if="inviteResult" label="">
            <el-alert type="success" :closable="false">
              <template #title>邀请码已生成</template>
              <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
                <el-input :value="inviteResult.code" readonly style="width:280px" />
                <el-button size="small" @click="copyInvite">复制</el-button>
              </div>
              <div style="margin-top:6px;color:#909399;font-size:12px">
                把这个码发给对方, 在登录页填写注册即可.
              </div>
            </el-alert>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="inviteDialog = false; inviteResult = null">关闭</el-button>
          <el-button type="primary" @click="createInvite">生成邀请码</el-button>
        </template>
      </el-dialog>

      <!-- ===== v0.8 审核 dialog ===== -->
      <el-dialog v-model="reviewDialog" :title="reviewForm.approve ? '✓ 批准注册申请' : '✗ 拒绝注册申请'" width="560px">
        <div v-if="reviewTarget" style="background:#f7fafc;padding:10px;border-radius:6px;margin-bottom:12px;font-size:13px">
          申请人: <strong>{{ reviewTarget.username }}</strong> ({{ reviewTarget.display_name }})<br>
          申请角色: <strong>{{ roleLabelOf(reviewTarget.requested_role) }}</strong><br>
          <span v-if="reviewTarget.agency_name">加入: <strong>{{ reviewTarget.agency_name }}</strong></span>
          <span v-else-if="reviewTarget.requested_agency_name" style="color:#e6a23c">
            🆕 申请新建社: <strong>{{ reviewTarget.requested_agency_name }}</strong>
          </span><br>
          <span v-if="reviewTarget.email">邮箱: {{ reviewTarget.email }}</span>
          <span v-if="reviewTarget.phone">手机: {{ reviewTarget.phone }}</span><br>
          理由: <em style="color:#606266">{{ reviewTarget.application_note || '—' }}</em>
        </div>
        <el-form :model="reviewForm" label-width="100px">
          <el-form-item label="决定">
            <el-radio-group v-model="reviewForm.approve">
              <el-radio-button :value="true">✓ 批准</el-radio-button>
              <el-radio-button :value="false">✗ 拒绝</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <template v-if="reviewForm.approve">
            <el-form-item label="角色">
              <el-select v-model="reviewForm.role" style="width:200px">
                <el-option v-if="myUserRole==='super_admin'" label="公司超管 super_admin" value="super_admin" />
                <el-option v-if="myUserRole==='super_admin'" label="公司 OP ops_manager" value="ops_manager" />
                <el-option label="旅行社老板 agency_owner" value="agency_owner" />
                <el-option label="业务员 agent" value="agent" />
                <el-option label="只读用户 viewer" value="viewer" />
              </el-select>
              <span v-if="reviewForm.role !== reviewTarget?.requested_role" style="color:#e6a23c;margin-left:8px;font-size:12px">
                ⚠ 与申请人选择的不同
              </span>
            </el-form-item>
            <el-form-item label="所属旅行社">
              <el-select v-model="reviewForm.agency_id" filterable clearable style="width:240px"
                :placeholder="reviewTarget?.requested_agency_name ? '留空则自动创建 ' + reviewTarget.requested_agency_name : '选择旅行社'">
                <el-option v-for="a in allAgencies" :key="a.id" :label="a.name" :value="a.id" />
              </el-select>
            </el-form-item>
          </template>
          <el-form-item label="审核备注">
            <el-input v-model="reviewForm.review_note" type="textarea" :rows="2"
              :placeholder="reviewForm.approve ? '可选, 给申请人留言' : '必填: 拒绝原因, 申请人会看到'" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="reviewDialog = false">取消</el-button>
          <el-button :type="reviewForm.approve ? 'success' : 'danger'" @click="submitReview">
            {{ reviewForm.approve ? '✓ 确认批准' : '✗ 确认拒绝' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- ===== v0.8.4 直接添加用户 dialog ===== -->
      <el-dialog v-model="createUserDialog" title="➕ 直接添加用户" width="560px">
        <el-alert type="info" :closable="false" style="margin-bottom:16px">
          <template #title>不需要邀请码 · 用户立即可用</template>
          <div style="font-size:12px;line-height:1.6">
            创建后的用户密码会被强制 force_password_change=true · 该用户首次登录时会被提示改密.
          </div>
        </el-alert>
        <el-form :model="createUserForm" label-width="100px" label-position="left">
          <el-form-item label="用户名 ★" required>
            <el-input v-model="createUserForm.username" placeholder="4 位以上 · 字母/数字/下划线" maxlength="40" show-word-limit />
          </el-form-item>
          <el-form-item label="初始密码 ★" required>
            <el-input v-model="createUserForm.password" type="password" show-password placeholder="至少 8 位" />
          </el-form-item>
          <el-form-item label="显示名">
            <el-input v-model="createUserForm.display_name" placeholder="选填 · 不填默认 = 用户名" />
          </el-form-item>
          <el-form-item label="角色 ★">
            <el-select v-model="createUserForm.role" style="width:240px">
              <el-option v-if="myUserRole==='super_admin'" label="公司超管 super_admin" value="super_admin" />
              <el-option v-if="myUserRole==='super_admin'" label="公司 OP ops_manager" value="ops_manager" />
              <el-option v-if="myUserRole==='super_admin'" label="旅行社老板 agency_owner" value="agency_owner" />
              <el-option label="业务员 agent" value="agent" />
              <el-option label="基础只读用户 viewer" value="viewer" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="myUserRole==='super_admin'" label="所属旅行社 ★">
            <el-select v-model="createUserForm.agency_id" filterable style="width:240px" placeholder="选择旅行社">
              <el-option v-for="a in allAgencies" :key="a.id" :label="a.name" :value="a.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="createUserForm.email" type="email" placeholder="选填" />
          </el-form-item>
          <el-form-item label="手机">
            <el-input v-model="createUserForm.phone" placeholder="选填" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createUserDialog = false">取消</el-button>
          <el-button type="success" @click="submitCreateUser">✓ 创建并立即生效</el-button>
        </template>
      </el-dialog>

      <!-- ===== v0.8.3 重置用户密码 dialog ===== -->
      <el-dialog v-model="resetPwdDialog" title="🔑 重置用户密码" width="460px">
        <div v-if="resetPwdTarget" style="background:#f7fafc;padding:10px;border-radius:6px;margin-bottom:12px;font-size:13px">
          目标用户: <strong>{{ resetPwdTarget.username }}</strong> ({{ resetPwdTarget.display_name }}) ·
          角色 <strong>{{ roleLabelOf(resetPwdTarget.role) }}</strong>
        </div>
        <el-form :model="resetPwdForm" label-width="100px">
          <el-form-item label="新密码 ★">
            <el-input v-model="resetPwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="resetPwdForm.force_change">强制对方下次登录改密</el-checkbox>
          </el-form-item>
        </el-form>
        <el-alert type="warning" :closable="false">
          <template #title>新密码会立即生效, 请用安全方式告知本人</template>
        </el-alert>
        <template #footer>
          <el-button @click="resetPwdDialog = false">取消</el-button>
          <el-button type="primary" @click="submitResetPwd">确认重置</el-button>
        </template>
      </el-dialog>

      <!-- ===== v0.8 旅行社编辑 dialog ===== -->
      <el-dialog v-model="agencyDialog" :title="agencyForm.id ? '编辑旅行社' : '新建旅行社'" width="560px">
        <el-form :model="agencyForm" label-width="100px">
          <el-form-item label="名称 ★">
            <el-input v-model="agencyForm.name" placeholder="如: 上海康辉" />
          </el-form-item>
          <el-form-item label="简称">
            <el-input v-model="agencyForm.short_name" placeholder="如: SHKH" maxlength="20" />
          </el-form-item>
          <el-form-item label="联系人">
            <el-input v-model="agencyForm.contact_person" />
          </el-form-item>
          <el-form-item label="电话">
            <el-input v-model="agencyForm.phone" />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="agencyForm.email" type="email" />
          </el-form-item>
          <el-form-item label="佣金率">
            <el-input-number v-model="agencyForm.commission_rate" :min="0" :max="0.5" :step="0.01" :precision="4" style="width:140px" />
            <span style="margin-left:8px;color:#909399;font-size:12px">0.05 = 5%</span>
          </el-form-item>
          <el-form-item label="状态">
            <el-radio-group v-model="agencyForm.status">
              <el-radio-button value="active">启用</el-radio-button>
              <el-radio-button value="suspended">停用</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="agencyDialog = false">取消</el-button>
          <el-button type="primary" @click="saveAgency">保存</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// ============================================================
//  报价历史
// ============================================================
const QuoteHistory = {
  props: ['destinations'],
  data() {
    return {
      quotes: [],
      loading: false,
      // 团结束反馈对话框
      feedbackVisible: false,
      feedbackForm: {
        quote_id: null,
        quote_no: '',
        actual_optional_revenue_cny: 0,
        actual_profit_cny: 0,
        won_or_lost: 'won',
        notes: '',
      },
      feedbackSubmitting: false,
    };
  },
  methods: {
    async load() {
      this.loading = true;
      try { this.quotes = (await http.get('/quotes')).data; }
      finally { this.loading = false; }
    },
    async del(id) {
      await http.delete(`/quotes/${id}`);
      ElementPlus.ElMessage.success('已删除');
      this.load();
    },
    exportUrl(id, format) {
      // 复用 axios 的 baseURL — API 已经是 /api/v1
      return `${API}/quotes/${id}/export?format=${format}`;
    },
    async download(id, format) {
      try {
        const r = await http.get(`/quotes/${id}/export`, {
          params: { format },
          responseType: 'blob',
        });
        // 解析 server-side filename
        const cd = r.headers['content-disposition'] || '';
        let filename = `BWS报价单_${id}.${format}`;
        const m = cd.match(/filename\*=UTF-8''([^;]+)/);
        if (m) filename = decodeURIComponent(m[1]);
        const blob = new Blob([r.data], { type: r.headers['content-type'] });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        ElementPlus.ElMessage.error('导出失败: ' + (e.response?.data?.detail || e.message));
      }
    },
    openFeedback(row) {
      this.feedbackForm = {
        quote_id: row.id,
        quote_no: row.quote_no,
        actual_optional_revenue_cny: 0,
        actual_profit_cny: 0,
        won_or_lost: 'won',
        notes: '',
      };
      this.feedbackVisible = true;
    },
    async submitFeedback() {
      this.feedbackSubmitting = true;
      try {
        const f = this.feedbackForm;
        await http.post(`/quotes/${f.quote_id}/feedback`, {
          actual_optional_revenue_cny: Number(f.actual_optional_revenue_cny) || 0,
          actual_profit_cny: Number(f.actual_profit_cny) || 0,
          won_or_lost: f.won_or_lost,
          notes: f.notes,
        });
        ElementPlus.ElMessage.success('反馈已提交,策略统计已更新');
        this.feedbackVisible = false;
      } catch (e) {
        ElementPlus.ElMessage.error('提交失败: ' + (e.response?.data?.detail || e.message));
      } finally {
        this.feedbackSubmitting = false;
      }
    }
  },
  mounted() { this.load(); },
  template: `
    <div class="bws-card">
      <h3>📋 报价历史</h3>
      <el-button @click="load" :loading="loading" size="small">刷新</el-button>
      <el-table :data="quotes" v-loading="loading" border stripe size="small" style="margin-top:12px">
        <el-table-column prop="quote_no" label="报价号" width="180" />
        <el-table-column prop="agency_name" label="B 端" />
        <el-table-column prop="customer_name" label="客户" />
        <el-table-column label="人数" width="80">
          <template #default="s">{{ s.row.pax_adult + s.row.pax_child }}</template>
        </el-table-column>
        <el-table-column prop="total_days" label="天数" width="60" />
        <el-table-column prop="free_days" label="自由" width="60" />
        <el-table-column prop="customer_type" label="类型" width="100" />
        <el-table-column label="售价/人" width="120">
          <template #default="s">¥ {{ s.row.price_cny_per_pax }}</template>
        </el-table-column>
        <el-table-column label="校验" width="100">
          <template #default="s">
            <el-tag :type="{pass:'success',warning:'warning',fail:'danger',unchecked:'info'}[s.row.feasibility_status]">
              {{ s.row.feasibility_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="导出" width="220">
          <template #default="s">
            <el-button size="small" type="success" link @click="download(s.row.id, 'xlsx')">📊 Excel</el-button>
            <el-button size="small" type="danger" link @click="download(s.row.id, 'pdf')">📄 PDF</el-button>
            <el-button size="small" type="primary" link @click="download(s.row.id, 'docx')">📝 Word</el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="s">
            <el-button type="warning" size="small" link @click="openFeedback(s.row)">✅ 团结束反馈</el-button>
            <el-button type="danger" size="small" link @click="del(s.row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-dialog v-model="feedbackVisible" title="团结束 · 实际自费回写" width="520px">
        <el-form :model="feedbackForm" label-width="160px" label-position="left">
          <el-form-item label="报价号">
            <span style="color:#606266">{{ feedbackForm.quote_no }}</span>
          </el-form-item>
          <el-form-item label="实际自费总收入 ¥">
            <el-input-number v-model="feedbackForm.actual_optional_revenue_cny" :min="0" :precision="2" style="width:200px" />
          </el-form-item>
          <el-form-item label="实际利润 ¥">
            <el-input-number v-model="feedbackForm.actual_profit_cny" :precision="2" style="width:200px" />
            <div style="color:#909399;font-size:12px">允许负数(亏损团也要记录)</div>
          </el-form-item>
          <el-form-item label="结果">
            <el-radio-group v-model="feedbackForm.won_or_lost">
              <el-radio-button label="won">赢 (达预期)</el-radio-button>
              <el-radio-button label="partial">部分 (有但低于预期)</el-radio-button>
              <el-radio-button label="lost">输 (未中)</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="feedbackForm.notes" type="textarea" :rows="3" placeholder="客户买了什么 / 原因 / 经验..." />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="feedbackVisible = false">取消</el-button>
          <el-button type="primary" :loading="feedbackSubmitting" @click="submitFeedback">提交反馈</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// ============================================================
//  v0.9.4 — 季节多档定价 / 附加费 / 节日捆绑包 管理面板
// ============================================================
const SEASON_BAND_OPTS = [
  { value: 'low',      label: '淡季',   color: '#909399' },
  { value: 'shoulder', label: '平季',   color: '#67c23a' },
  { value: 'high',     label: '旺季',   color: '#e6a23c' },
  { value: 'peak',     label: '高峰',   color: '#f56c6c' },
  { value: 'holiday',  label: '节日',   color: '#9b59b6' },
];

const CHARGE_TYPE_OPTS = [
  { value: 'tax',                 label: '政府税' },
  { value: 'service_fee',         label: '服务费' },
  { value: 'resort_fee',          label: '度假村费' },
  { value: 'tourist_tax',         label: '旅游税' },
  { value: 'summer_break',        label: '🏖 暑期附加 (7-8 月)' },
  { value: 'winter_break',        label: '❄️ 寒假附加 (1-2 月)' },
  { value: 'national_day_break',  label: '🇨🇳 国庆附加 (10/1-10/7)' },
  { value: 'other',               label: '其他' },
];

const CALC_METHOD_OPTS = [
  { value: 'percent',                label: '百分比 (在房费上叠加)' },
  { value: 'fixed_per_room_night',   label: 'IDR/房/晚' },
  { value: 'fixed_per_pax_night',    label: 'IDR/人/晚' },
  { value: 'fixed_per_stay',         label: 'IDR/整次入住' },
];

const SeasonalPricingManager = {
  props: ['destinations'],
  data() {
    return {
      activeSubTab: 'calendar',
      loading: false,
      calendars: [],
      surcharges: [],
      packages: [],
      hotels: [],          // 用于 packages/surcharges 关联酒店下拉
      editDialog: false,
      editKind: '',        // calendar | surcharge | package
      editForm: {},
      saving: false,
      // 选项常量(透传到模板)
      SEASON_BAND_OPTS,
      CHARGE_TYPE_OPTS,
      CALC_METHOD_OPTS,
    };
  },
  watch: {
    activeSubTab(v) { this.loadSubTab(v); },
  },
  computed: {
    hotelMap() {
      const m = {};
      this.hotels.forEach(h => { m[h.id] = h.name_zh; });
      return m;
    },
  },
  async mounted() {
    // 预载酒店列表(packages / surcharges 用)
    try {
      const r = await http.get('/resources/hotels');
      this.hotels = r.data || [];
    } catch (e) { /* 静默 */ }
    this.loadSubTab(this.activeSubTab);
  },
  methods: {
    bandMeta(code) {
      return SEASON_BAND_OPTS.find(o => o.value === code) || { label: code, color: '#909399' };
    },
    async loadSubTab(tab) {
      this.loading = true;
      try {
        if (tab === 'calendar') {
          this.calendars = (await http.get('/resources/season-calendars')).data;
        } else if (tab === 'surcharge') {
          this.surcharges = (await http.get('/resources/surcharges')).data;
        } else if (tab === 'package') {
          this.packages = (await http.get('/resources/hotel-packages')).data;
        }
      } catch (e) {
        ElementPlus.ElMessage.error('加载失败:' + (e.message || e));
      } finally { this.loading = false; }
    },
    openCreate(kind) {
      this.editKind = kind;
      if (kind === 'calendar') {
        this.editForm = { name: '', season_band: 'shoulder', date_from: '', date_to: '',
                          priority: 0, destination_code: null, note: '' };
      } else if (kind === 'surcharge') {
        this.editForm = { hotel_id: null, name: '', charge_type: 'tax', calc_method: 'percent',
                          amount: 0, season_band: null, valid_from: null, valid_to: null,
                          active: true, note: '' };
      } else if (kind === 'package') {
        this.editForm = { hotel_id: null, name: '', season_band: 'holiday',
                          valid_from: '', valid_to: '', mandatory: true,
                          cost_idr_per_room: 0, cost_idr_per_pax: 0,
                          includes: '', replaces_dinner: false, active: true, note: '' };
      }
      this.editDialog = true;
    },
    openEdit(kind, row) {
      this.editKind = kind;
      this.editForm = { ...row };
      this.editDialog = true;
    },
    async save() {
      this.saving = true;
      try {
        const paths = {
          calendar: '/resources/season-calendars',
          surcharge: '/resources/surcharges',
          package: '/resources/hotel-packages',
        };
        // 简单校验
        if (this.editKind === 'calendar') {
          if (!this.editForm.name || !this.editForm.date_from || !this.editForm.date_to) {
            ElementPlus.ElMessage.warning('名称/起始日期/结束日期必填'); this.saving = false; return;
          }
        } else if (this.editKind === 'package') {
          if (!this.editForm.hotel_id || !this.editForm.name || !this.editForm.valid_from || !this.editForm.valid_to) {
            ElementPlus.ElMessage.warning('酒店/名称/有效期必填'); this.saving = false; return;
          }
        } else if (this.editKind === 'surcharge') {
          if (!this.editForm.name) {
            ElementPlus.ElMessage.warning('附加费名称必填'); this.saving = false; return;
          }
        }
        await http.post(paths[this.editKind], this.editForm);
        ElementPlus.ElMessage.success('已保存');
        this.editDialog = false;
        const tabMap = { calendar: 'calendar', surcharge: 'surcharge', package: 'package' };
        this.loadSubTab(tabMap[this.editKind]);
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败:' + (e.response?.data?.detail || e.message));
      } finally { this.saving = false; }
    },
    async remove(kind, row) {
      try {
        await ElementPlus.ElMessageBox.confirm(`确认删除 ${row.name}?`, '提示', { type: 'warning' });
      } catch (e) { return; }
      const paths = {
        calendar: `/resources/season-calendars/${row.id}`,
        surcharge: `/resources/surcharges/${row.id}`,
        package: `/resources/hotel-packages/${row.id}`,
      };
      try {
        await http.delete(paths[kind]);
        ElementPlus.ElMessage.success('已删除');
        this.loadSubTab(kind);
      } catch (e) {
        ElementPlus.ElMessage.error('删除失败:' + e.message);
      }
    },
    fmtIDR(v) {
      if (v == null) return '—';
      const n = Number(v);
      if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
      if (n >= 1_000)     return (n / 1_000).toFixed(0) + 'k';
      return n.toString();
    },
  },
  template: `
    <div class="seasonal-pricing-manager">
      <el-alert type="info" :closable="false" style="margin-bottom:12px">
        <strong>季节多档定价 · v0.9.4</strong> ·
        全局季节日历定档(淡/平/旺/高峰/节日),酒店附加费(税/旅游税),节日捆绑包(圣诞 Gala / 新年烟花)。
        计价时:日期 → 季节档 → 房型对应价 + 叠加附加费 + 强制节日包。
      </el-alert>

      <el-tabs v-model="activeSubTab" type="border-card">

        <!-- ============= 季节日历 ============= -->
        <el-tab-pane label="📅 季节日历" name="calendar">
          <div style="margin-bottom:10px">
            <el-button type="primary" size="small" @click="openCreate('calendar')">+ 新增日历区间</el-button>
            <span style="color:#909399;font-size:12px;margin-left:12px">
              区间重叠时按 priority 大优先 (节日=10 / 高峰=8 / 旺=5 / 平=2 / 淡=1 建议值)
            </span>
          </div>
          <el-table :data="calendars" v-loading="loading" border stripe size="small">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="季节档" width="100">
              <template #default="s">
                <el-tag :style="{background: bandMeta(s.row.season_band).color, color:'#fff', border:'none'}">
                  {{ bandMeta(s.row.season_band).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="date_from" label="起" width="110" />
            <el-table-column prop="date_to"   label="止" width="110" />
            <el-table-column prop="priority" label="优先级" width="80" align="right" />
            <el-table-column prop="destination_code" label="目的地" width="80">
              <template #default="s">{{ s.row.destination_code || '全部' }}</template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="s">
                <el-button size="small" @click="openEdit('calendar', s.row)">改</el-button>
                <el-button size="small" type="danger" @click="remove('calendar', s.row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============= 附加费 ============= -->
        <el-tab-pane label="💰 附加费" name="surcharge">
          <div style="margin-bottom:10px">
            <el-button type="primary" size="small" @click="openCreate('surcharge')">+ 新增附加费</el-button>
            <span style="color:#909399;font-size:12px;margin-left:12px">
              hotel 留空 = 全局生效(适合政府税/旅游税);设 hotel 后仅该酒店应用
            </span>
          </div>
          <el-table :data="surcharges" v-loading="loading" border stripe size="small">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="类型" width="100">
              <template #default="s">
                {{ (CHARGE_TYPE_OPTS.find(o => o.value === s.row.charge_type) || {}).label || s.row.charge_type }}
              </template>
            </el-table-column>
            <el-table-column label="计算方式" min-width="170">
              <template #default="s">
                {{ (CALC_METHOD_OPTS.find(o => o.value === s.row.calc_method) || {}).label || s.row.calc_method }}
              </template>
            </el-table-column>
            <el-table-column label="金额/比率" width="120" align="right">
              <template #default="s">
                <strong>{{ s.row.calc_method === 'percent' ? (s.row.amount + '%') : fmtIDR(s.row.amount) }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="适用酒店" width="160">
              <template #default="s">
                {{ s.row.hotel_id ? (hotelMap[s.row.hotel_id] || ('#' + s.row.hotel_id)) : '全部' }}
              </template>
            </el-table-column>
            <el-table-column prop="season_band" label="限定季节" width="100">
              <template #default="s">{{ s.row.season_band || '全部' }}</template>
            </el-table-column>
            <el-table-column label="启用" width="60" align="center">
              <template #default="s">{{ s.row.active ? '✓' : '✗' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="s">
                <el-button size="small" @click="openEdit('surcharge', s.row)">改</el-button>
                <el-button size="small" type="danger" @click="remove('surcharge', s.row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============= 节日捆绑包 ============= -->
        <el-tab-pane label="🎄 节日捆绑包" name="package">
          <div style="margin-bottom:10px">
            <el-button type="primary" size="small" @click="openCreate('package')">+ 新增捆绑包</el-button>
            <span style="color:#909399;font-size:12px;margin-left:12px">
              mandatory=true 时,在有效期内住该酒店自动叠加;replaces_dinner=true 会跳过当晚另设的晚餐
            </span>
          </div>
          <el-table :data="packages" v-loading="loading" border stripe size="small">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="酒店" width="180">
              <template #default="s">{{ hotelMap[s.row.hotel_id] || ('#' + s.row.hotel_id) }}</template>
            </el-table-column>
            <el-table-column prop="valid_from" label="起" width="110" />
            <el-table-column prop="valid_to"   label="止" width="110" />
            <el-table-column label="强制" width="60" align="center">
              <template #default="s">{{ s.row.mandatory ? '✓' : '—' }}</template>
            </el-table-column>
            <el-table-column label="房费 IDR" width="100" align="right">
              <template #default="s">{{ fmtIDR(s.row.cost_idr_per_room) }}</template>
            </el-table-column>
            <el-table-column label="人头 IDR" width="100" align="right">
              <template #default="s">{{ fmtIDR(s.row.cost_idr_per_pax) }}</template>
            </el-table-column>
            <el-table-column label="替换晚餐" width="80" align="center">
              <template #default="s">{{ s.row.replaces_dinner ? '✓' : '—' }}</template>
            </el-table-column>
            <el-table-column prop="includes" label="包含" min-width="150" show-overflow-tooltip />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="s">
                <el-button size="small" @click="openEdit('package', s.row)">改</el-button>
                <el-button size="small" type="danger" @click="remove('package', s.row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <!-- ============= 编辑 Dialog ============= -->
      <el-dialog v-model="editDialog" :title="(editForm.id ? '编辑' : '新增') + ' · ' +
                ({calendar:'季节日历', surcharge:'附加费', package:'节日捆绑包'}[editKind] || '')" width="600px">
        <el-form label-position="top" v-if="editKind === 'calendar'">
          <el-form-item label="名称 ★">
            <el-input v-model="editForm.name" placeholder="如: 2026 圣诞新年旺季" />
          </el-form-item>
          <el-form-item label="季节档 ★">
            <el-select v-model="editForm.season_band" style="width:100%">
              <el-option v-for="o in SEASON_BAND_OPTS" :key="o.value" :value="o.value" :label="o.label" />
            </el-select>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="起始日期 ★">
              <el-date-picker v-model="editForm.date_from" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="结束日期 ★">
              <el-date-picker v-model="editForm.date_to" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="优先级 (越大越优先)">
              <el-input-number v-model="editForm.priority" :min="0" :max="100" />
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="目的地 (留空=全部)">
              <el-select v-model="editForm.destination_code" clearable style="width:100%">
                <el-option v-for="d in destinations" :key="d.id" :value="d.code" :label="d.name_zh + ' (' + d.code + ')'" />
              </el-select>
            </el-form-item></el-col>
          </el-row>
          <el-form-item label="备注">
            <el-input v-model="editForm.note" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>

        <el-form label-position="top" v-if="editKind === 'surcharge'">
          <el-form-item label="名称 ★">
            <el-input v-model="editForm.name" placeholder="如: Government Tax 21%" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="类型 ★">
              <el-select v-model="editForm.charge_type" style="width:100%">
                <el-option v-for="o in CHARGE_TYPE_OPTS" :key="o.value" :value="o.value" :label="o.label" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="计算方式 ★">
              <el-select v-model="editForm.calc_method" style="width:100%">
                <el-option v-for="o in CALC_METHOD_OPTS" :key="o.value" :value="o.value" :label="o.label" />
              </el-select>
            </el-form-item></el-col>
          </el-row>
          <el-form-item :label="editForm.calc_method === 'percent' ? '百分比 (如 21 = 21%)' : '金额 IDR'">
            <el-input-number v-model="editForm.amount" :min="0" :step="editForm.calc_method === 'percent' ? 0.5 : 10000" style="width:100%" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="适用酒店 (留空=全部)">
              <el-select v-model="editForm.hotel_id" clearable filterable style="width:100%">
                <el-option v-for="h in hotels" :key="h.id" :value="h.id" :label="h.name_zh" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="限定季节 (留空=全部; 多档逗号 high,peak)">
              <el-input v-model="editForm.season_band" placeholder="如 high,peak,holiday" clearable />
            </el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="生效起 (可空)">
              <el-date-picker v-model="editForm.valid_from" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="生效止 (可空)">
              <el-date-picker v-model="editForm.valid_to" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
          </el-row>
          <el-form-item>
            <el-switch v-model="editForm.active" active-text="启用" inactive-text="禁用" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="editForm.note" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>

        <el-form label-position="top" v-if="editKind === 'package'">
          <el-form-item label="酒店 ★">
            <el-select v-model="editForm.hotel_id" filterable style="width:100%">
              <el-option v-for="h in hotels" :key="h.id" :value="h.id" :label="h.name_zh" />
            </el-select>
          </el-form-item>
          <el-form-item label="名称 ★">
            <el-input v-model="editForm.name" placeholder="如: 圣诞夜 Gala Dinner" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="有效起 ★">
              <el-date-picker v-model="editForm.valid_from" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="有效止 ★">
              <el-date-picker v-model="editForm.valid_to" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="季节档">
              <el-select v-model="editForm.season_band" style="width:100%">
                <el-option v-for="o in SEASON_BAND_OPTS" :key="o.value" :value="o.value" :label="o.label" />
              </el-select>
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item>
              <el-switch v-model="editForm.mandatory" active-text="强制叠加" inactive-text="可选" />
            </el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="房费 IDR (按房算)">
              <el-input-number v-model="editForm.cost_idr_per_room" :min="0" :step="100000" style="width:100%" />
            </el-form-item></el-col>
            <el-col :span="12"><el-form-item label="人头费 IDR (按人算)">
              <el-input-number v-model="editForm.cost_idr_per_pax" :min="0" :step="50000" style="width:100%" />
            </el-form-item></el-col>
          </el-row>
          <el-form-item label="包含内容">
            <el-input v-model="editForm.includes" type="textarea" :rows="2" placeholder="如: Gala Dinner + 烟花 + 红酒 1 瓶" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="editForm.replaces_dinner" active-text="替换当晚晚餐" inactive-text="另算" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="editForm.active" active-text="启用" inactive-text="禁用" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="editForm.note" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="editDialog = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </template>
      </el-dialog>
    </div>
  `
};

// 注册全局组件
window.__BWS_COMPONENTS = {
  QuoteBuilder, ResourceManager, AiUploader,
  TemplateManager, SettingsPanel, QuoteHistory,
  SeasonalPricingManager,
};
