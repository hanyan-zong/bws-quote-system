/* BWS 预报价系统 · 主入口 */

const { createApp, ref } = Vue;
axios.defaults.withCredentials = true;
const httpRoot = axios.create({ baseURL: API, timeout: 60000, withCredentials: true });

const App = {
  data() {
    return {
      activeTab: 'quote',
      destinations: [],
      hotels: [], attractions: [], restaurants: [],
      vehicles: [], guides: [], templates: [],
      spas: [], waters: [], teas: [], optionals: [],
      rate: null,
      aiAvailable: false,
      today: new Date().toISOString().slice(0, 10),
      zhCn: ElementPlusLocaleZhCn,
      // 口令门
      authRequired: true,  // v0.8.1: 永远 true (用户系统强制启用)
      authenticated: false,
      loginUsername: '',
      loginPassword: '',
      loginError: '',
      loginLoading: false,
      // v0.7: 用户/配额/权限
      currentUser: null,
      roleLabel: '',
      myQuotas: [],
      myFeatures: [],
      quotaDialog: false,
      quotaLoading: false,
      // v0.8: 多步注册向导
      authMode: 'select',          // select|login|register-invite|register-public
      regInviteStep: 1,            // 邀请码注册步骤
      regPublicStep: 1,            // 自助申请步骤
      regError: '',
      regSuccess: '',
      regLoading: false,
      regForm: {
        code: '', invitationInfo: null,
        username: '', password: '', display_name: '', email: '', phone: '',
      },
      appForm: {
        agency_choice: 'existing', // existing | new
        agency_id: null, requested_agency_name: '',
        requested_role: 'agent',
        username: '', password: '', display_name: '',
        email: '', phone: '', application_note: '',
      },
      publicAgencies: [],
      // v0.8.3 主密钥自助解锁
      masterUnlockDialog: false,
      masterUnlockLoading: false,
      masterUnlockError: '',
      masterUnlockSuccess: '',
      masterUnlockForm: { master_password: '', target_username: '', reset_password_to: '' },
      // v0.8.3 改密
      changePasswordDialog: false,
      changePasswordLoading: false,
      changePasswordError: '',
      changePasswordForm: { old_password: '', new_password: '', new_password_confirm: '' },
    };
  },
  computed: {
    // v0.9.2: 普通用户 (agent / viewer) 看不到资源库/AI 采集/一日游模板/设置
    isAdmin() {
      const role = this.currentUser?.role;
      return ['super_admin', 'ops_manager', 'agency_owner'].includes(role);
    },
  },
  methods: {
    async loadHealth() {
      try {
        const r = await httpRoot.get('/health');
        this.aiAvailable = r.data.ai_available;
      } catch (e) {
        console.error(e);
      }
    },
    async loadRate() {
      try { this.rate = (await httpRoot.get('/settings/exchange-rate')).data; }
      catch (e) { console.error(e); }
    },
    async loadAllResources() {
      try {
        const [d, h, a, r, v, g, t, sp, wa, tea, opt] = await Promise.all([
          httpRoot.get('/resources/destinations'),
          httpRoot.get('/resources/hotels'),
          httpRoot.get('/resources/attractions'),
          httpRoot.get('/resources/restaurants'),
          httpRoot.get('/resources/vehicles'),
          httpRoot.get('/resources/guides'),
          httpRoot.get('/templates'),
          httpRoot.get('/resources/simple/spa'),
          httpRoot.get('/resources/simple/water'),
          httpRoot.get('/resources/simple/tea'),
          httpRoot.get('/resources/optional-tours'),
        ]);
        this.destinations = d.data;
        this.hotels = h.data;
        this.attractions = a.data;
        this.restaurants = r.data;
        this.vehicles = v.data;
        this.guides = g.data;
        this.templates = t.data;
        this.spas = sp.data;
        this.waters = wa.data;
        this.teas = tea.data;
        this.optionals = opt.data;
      } catch (e) {
        console.error('资源加载失败', e);
        ElementPlus.ElMessage.error('资源加载失败：' + (e.response?.data?.detail || e.message));
      }
    },
    async loadTemplates() {
      this.templates = (await httpRoot.get('/templates')).data;
    },
    onQuoteSaved() { /* 留 hook */ },
    openMindMap() {
      window.open('/mindmap', '_blank');
    },
    async loadAfterAuth() {
      await this.loadHealth();
      await this.loadRate();
      await this.loadAllResources();
      await this.loadMe();        // v0.7: 拉用户/配额/权限
    },
    async loadMe() {
      // 拉当前用户 + permissions + quotas
      try {
        const meR = await httpRoot.get('/auth/me');
        this.currentUser = meR.data;
      } catch (e) { /* 关闭口令门时无 /me */ this.currentUser = null; }
      try {
        const permR = await httpRoot.get('/auth/permissions');
        this.roleLabel = permR.data.role_label || '';
        this.myFeatures = permR.data.features || [];
      } catch (e) {}
    },
    async loadAndShowQuotas() {
      this.quotaLoading = true;
      this.quotaDialog = true;
      try {
        const r = await httpRoot.get('/auth/quotas');
        this.myQuotas = r.data.quotas || [];
      } catch (e) {
        ElementPlus.ElMessage.error('拉取配额失败: ' + (e.response?.data?.detail || e.message));
      } finally {
        this.quotaLoading = false;
      }
    },
    async checkAuth() {
      try {
        const r = await httpRoot.get('/auth/status');
        // v0.8.1: 用户系统强制启用, authRequired 永远 true
        this.authRequired = true;
        this.authenticated = !!r.data.authenticated;
      } catch (e) {
        console.error('auth/status 调用失败', e);
        this.authenticated = false;
      }
    },
    async doLogin() {
      if (!this.loginUsername || !this.loginPassword) {
        this.loginError = '请输入账号和密码';
        return;
      }
      this.loginLoading = true;
      this.loginError = '';
      try {
        await httpRoot.post('/auth/login', {
          username: this.loginUsername,
          password: this.loginPassword,
        });
        this.authenticated = true;
        this.loginUsername = '';
        this.loginPassword = '';
        await this.loadAfterAuth();
        ElementPlus.ElMessage.success('登录成功');
      } catch (e) {
        this.loginError = e.response?.data?.detail || '登录失败';
      } finally {
        this.loginLoading = false;
      }
    },
    onUserMenuCmd(cmd) {
      // v0.8.4 用户菜单 dropdown
      if (cmd === 'quotas')    return this.loadAndShowQuotas();
      if (cmd === 'changepwd') return this.changePasswordDialog = true;
      if (cmd === 'logout')    return this.logout();
    },
    async logout() {
      try { await httpRoot.post('/auth/logout'); } catch (e) {}
      this.authenticated = false;
      this.currentUser = null;
      this.roleLabel = '';
      this.myQuotas = [];
      this.authMode = 'select';
      ElementPlus.ElMessage.info('已退出登录');
    },
    cancelLogin() {
      this.loginUsername = '';
      this.loginPassword = '';
      this.loginError = '';
    },

    // ============ v0.8 多步注册向导 ============
    resetAuthFlow() {
      this.authMode = 'select';
      this.regInviteStep = 1;
      this.regPublicStep = 1;
      this.regError = '';
      this.regSuccess = '';
      this.regLoading = false;
      this.regForm = { code: '', invitationInfo: null, username: '', password: '', display_name: '', email: '', phone: '' };
      this.appForm = {
        agency_choice: 'existing', agency_id: null, requested_agency_name: '',
        requested_role: 'agent', username: '', password: '', display_name: '',
        email: '', phone: '', application_note: '',
      };
    },
    goRegisterInvite() {
      this.resetAuthFlow();
      this.authMode = 'register-invite';
    },
    async goRegisterPublic() {
      this.resetAuthFlow();
      this.authMode = 'register-public';
      // 拉公开旅行社列表
      try {
        const r = await httpRoot.get('/auth/agencies-public');
        this.publicAgencies = r.data || [];
      } catch (e) {
        this.publicAgencies = [];
      }
    },
    async verifyInvite() {
      if (!this.regForm.code) { this.regError = '请输入邀请码'; return; }
      // 已校验过 → 直接走下一步
      if (this.regForm.invitationInfo) {
        this.regError = '';
        this.regInviteStep = 2;
        return;
      }
      this.regLoading = true;
      this.regError = '';
      try {
        const r = await httpRoot.get(`/auth/invitation/${encodeURIComponent(this.regForm.code)}`);
        const info = r.data;
        const roleMap = {
          super_admin: '公司超管', ops_manager: '公司 OP',
          agency_owner: '旅行社老板', agent: '业务员', viewer: '只读用户',
        };
        this.regForm.invitationInfo = {
          agency_name: info.agency?.name || '—',
          role: info.role,
          role_label: roleMap[info.role] || info.role,
          uses_remaining: info.uses_remaining,
        };
      } catch (e) {
        this.regError = e.response?.data?.detail || '邀请码无效';
      } finally {
        this.regLoading = false;
      }
    },
    async submitRegisterInvite() {
      this.regError = '';
      const f = this.regForm;
      if (!f.username || f.username.length < 4) { this.regError = '用户名至少 4 字符'; return; }
      if (!f.password || f.password.length < 8) { this.regError = '密码至少 8 位'; return; }
      this.regLoading = true;
      try {
        const r = await httpRoot.post('/auth/register', {
          code: f.code, username: f.username, password: f.password,
          display_name: f.display_name || null, email: f.email || null, phone: f.phone || null,
        });
        // 注册成功 → 自动登录
        this.authenticated = true;
        this.resetAuthFlow();
        await this.loadAfterAuth();
        ElementPlus.ElMessage.success(`✓ 注册成功并已登录: ${r.data.user.username}`);
      } catch (e) {
        this.regError = e.response?.data?.detail || '注册失败';
      } finally {
        this.regLoading = false;
      }
    },
    goPublicStep2() {
      const f = this.appForm;
      if (f.agency_choice === 'existing' && !f.agency_id) {
        this.regError = '请选择要加入的旅行社'; return;
      }
      if (f.agency_choice === 'new' && !f.requested_agency_name) {
        this.regError = '请填写新旅行社名称'; return;
      }
      this.regError = '';
      this.regPublicStep = 2;
    },
    goPublicStep3() {
      const f = this.appForm;
      if (!f.username || f.username.length < 4) { this.regError = '用户名至少 4 字符'; return; }
      if (!f.password || f.password.length < 8) { this.regError = '密码至少 8 位'; return; }
      this.regError = '';
      this.regPublicStep = 3;
    },
    async doChangePassword() {
      this.changePasswordError = '';
      const f = this.changePasswordForm;
      if (!f.old_password || !f.new_password) { this.changePasswordError = '请输入旧密码和新密码'; return; }
      if (f.new_password.length < 8) { this.changePasswordError = '新密码至少 8 位'; return; }
      if (f.new_password !== f.new_password_confirm) { this.changePasswordError = '两次输入的新密码不一致'; return; }
      this.changePasswordLoading = true;
      try {
        await httpRoot.post('/auth/change-password', {
          old_password: f.old_password, new_password: f.new_password,
        });
        ElementPlus.ElMessage.success('✓ 密码已修改');
        this.changePasswordDialog = false;
        this.changePasswordForm = { old_password: '', new_password: '', new_password_confirm: '' };
        // 刷新 currentUser 让 banner 消失
        if (this.currentUser) this.currentUser.force_password_change = false;
        await this.loadMe();
      } catch (e) {
        this.changePasswordError = e.response?.data?.detail || '修改失败';
      } finally {
        this.changePasswordLoading = false;
      }
    },

    async doMasterUnlock() {
      this.masterUnlockError = '';
      this.masterUnlockSuccess = '';
      if (!this.masterUnlockForm.master_password) {
        this.masterUnlockError = '请输入主密钥';
        return;
      }
      this.masterUnlockLoading = true;
      try {
        const r = await httpRoot.post('/auth/master-unlock', {
          master_password: this.masterUnlockForm.master_password,
          target_username: this.masterUnlockForm.target_username || null,
          reset_password_to: this.masterUnlockForm.reset_password_to || null,
        });
        this.masterUnlockSuccess = r.data.message + ' · 请用解锁后的账号登录';
        // 自动填回登录框
        if (r.data.username) {
          this.loginUsername = r.data.username;
        }
        this.loginError = '';
        // 3 秒后自动关 dialog
        setTimeout(() => {
          this.masterUnlockDialog = false;
          this.masterUnlockSuccess = '';
          this.masterUnlockForm = { master_password: '', target_username: '', reset_password_to: '' };
        }, 3000);
      } catch (e) {
        this.masterUnlockError = e.response?.data?.detail || '操作失败';
      } finally {
        this.masterUnlockLoading = false;
      }
    },

    async submitRegisterPublic() {
      const f = this.appForm;
      this.regLoading = true;
      this.regError = '';
      try {
        const payload = {
          username: f.username, password: f.password,
          display_name: f.display_name || null,
          email: f.email || null, phone: f.phone || null,
          requested_role: f.requested_role,
          agency_id: f.agency_choice === 'existing' ? f.agency_id : null,
          requested_agency_name: f.agency_choice === 'new' ? f.requested_agency_name : null,
          application_note: f.application_note || null,
        };
        const r = await httpRoot.post('/auth/register-public', payload);
        this.regSuccess = r.data.message || '申请已提交,等待管理员审核';
      } catch (e) {
        this.regError = e.response?.data?.detail || '申请提交失败';
      } finally {
        this.regLoading = false;
      }
    },
  },
  async mounted() {
    // 全局 401 拦截:cookie 过期就重新弹登录
    httpRoot.interceptors.response.use(
      r => r,
      err => {
        if (err.response?.status === 401) {
          this.authenticated = false;
        }
        return Promise.reject(err);
      }
    );
    await this.checkAuth();
    if (this.authenticated) {
      await this.loadAfterAuth();
    }
  }
};

const app = createApp(App);
app.use(ElementPlus);

// 注册图标
for (const [name, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, comp);
}

// 注册我们的组件
const C = window.__BWS_COMPONENTS || {};
app.component('quote-builder', C.QuoteBuilder);
app.component('resource-manager', C.ResourceManager);
app.component('ai-uploader', C.AiUploader);
app.component('template-manager', C.TemplateManager);
app.component('settings-panel', C.SettingsPanel);
app.component('quote-history', C.QuoteHistory);

app.mount('#app');
