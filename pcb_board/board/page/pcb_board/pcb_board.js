// Team-Board — native ERPNext Desk-Page.
// UI-Design 1:1 aus scripts/render_dashboard.py (Hauptrepo) nach JS portiert:
// PCB-Logo, Tabs (Posteingang/Umsatz/Abrechnung), Postfach-Chips, aufklappbare
// Mail-Karten mit Kopieren-Button, Meter/Chart/Coverage/Tips, Abrechnungstabellen.
// Unterschied zum Artifact-/Webapp-Board: Daten kommen per frappe.call() aus dieser
// ERPNext-Instanz selbst (siehe pcb_board/api.py), Login = normales ERPNext-Login.

frappe.pages['pcb-board'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Team-Board',
		single_column: true,
	});
	new PCBBoard(page);
};

function PCBBoard(page) {
	this.page = page;
	this.$root = $(page.body);
	this.selMb = 'all';
	this.selCat = 'all';
	this.q = '';
	this.qRaw = '';
	this.metrics = null;
	this._openMids = {};
	this._openPos = {};
	this._openWos = {};
	// Sortierung/Filter der Produktionsauftragsliste — überlebt Neurendern.
	this._woSort = { key: 'customer_due_date', dir: 1 };
	this._woFilter = 'all';
	this._woQuery = '';

	this.injectStyle();
	this.$root.html(this.shellHtml());
	this.$overlay = this.$root.find('#pcb-overlay');
	this.$toast = this.$root.find('#pcb-toast');

	this.bindStatic();
	this.handleUrlParams();
	this.load();
	this.pollTimer = setInterval(() => this.pollStatus(), 4000);
}

// ------------------------------------------------------------------ Helpers

PCBBoard.prototype.eur = function (v) {
	v = Number(v || 0);
	var s = v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
	return s + ' €';
};

PCBBoard.prototype.pct = function (v) {
	return Math.round((v || 0) * 100) + ' %';
};

PCBBoard.prototype.esc = function (s) {
	return frappe.utils.escape_html(String(s == null ? '' : s));
};

PCBBoard.prototype.shortBox = function (email) {
	return (email || '').split('@')[0] || email;
};

PCBBoard.prototype.toast = function (msg) {
	var t = this.$toast;
	t.text(msg).addClass('show');
	setTimeout(function () {
		t.removeClass('show');
	}, 1600);
};

PCBBoard.prototype.nextRefreshIn = function () {
	var now = new Date();
	var d = new Date(now);
	// nächster :00 oder :30
	var m = d.getMinutes();
	d.setSeconds(0); d.setMilliseconds(0);
	if (m < 30) { d.setMinutes(30); } else { d.setMinutes(0); d.setHours(d.getHours() + 1); }
	// Wenn außerhalb 6-18 Uhr oder Wochenende: nächsten gültigen Slot finden
	for (var i = 0; i < 200; i++) {
		var day = d.getDay(); // 0=So, 6=Sa
		var h = d.getHours();
		if (day >= 1 && day <= 5 && h >= 6 && h <= 18) break;
		d = new Date(d.getTime() + 30 * 60 * 1000);
	}
	var diff = Math.max(0, Math.round((d - now) / 1000));
	if (diff >= 3600) return Math.floor(diff / 3600) + ' h ' + Math.floor((diff % 3600) / 60) + ' min';
	if (diff >= 60) return Math.floor(diff / 60) + ' min';
	return diff + ' s';
};

PCBBoard.prototype.pcbLogoSvg = function (size, animated, cls) {
	var cx = 100, cy = 100, rOut = 94, rIn = 54, disc = 38, pad = 5, redIndex = 1;
	var segs = '';
	for (var k = 0; k < 8; k++) {
		var a0 = ((k * 45 + pad - 90) * Math.PI) / 180;
		var a1 = (((k + 1) * 45 - pad - 90) * Math.PI) / 180;
		var x0o = cx + rOut * Math.cos(a0), y0o = cy + rOut * Math.sin(a0);
		var x1o = cx + rOut * Math.cos(a1), y1o = cy + rOut * Math.sin(a1);
		var x0i = cx + rIn * Math.cos(a0), y0i = cy + rIn * Math.sin(a0);
		var x1i = cx + rIn * Math.cos(a1), y1i = cy + rIn * Math.sin(a1);
		var d = 'M' + x0o.toFixed(2) + ',' + y0o.toFixed(2) + ' A' + rOut + ',' + rOut + ' 0 0 1 ' +
			x1o.toFixed(2) + ',' + y1o.toFixed(2) + ' L' + x1i.toFixed(2) + ',' + y1i.toFixed(2) +
			' A' + rIn + ',' + rIn + ' 0 0 0 ' + x0i.toFixed(2) + ',' + y0i.toFixed(2) + ' Z';
		var color = k === redIndex ? 'pcb-red' : 'pcb-teal';
		segs += '<path class="pcb-seg ' + color + '" style="--i:' + k + '" d="' + d + '"/>';
	}
	var discEl = '<circle class="pcb-teal pcb-disc" cx="100" cy="100" r="' + disc + '"/>';
	var klass = 'pcb-logo' + (animated ? ' pulsing' : '') + (cls ? ' ' + cls : '');
	return '<svg class="' + klass + '" viewBox="0 0 200 200" width="' + size + '" height="' + size +
		'" aria-label="Musterfirma" role="img">' + segs + discEl + '</svg>';
};

// -------------------------------------------------------------- CSS + Shell

PCBBoard.prototype.injectStyle = function () {
	if (document.getElementById('pcb-board-style')) return;
	var css = document.createElement('style');
	css.id = 'pcb-board-style';
	css.textContent = PCB_BOARD_CSS;
	document.head.appendChild(css);
};

PCBBoard.prototype.shellHtml = function () {
	return (
		'<div class="pcb-root">' +
		'<div class="hd">' +
		'<div class="brand">' + this.pcbLogoSvg(46, false, '') +
		'<div><h1 id="pcb-h1">Team-Board</h1><div class="tag">Sekretariat</div>' +
		'<div class="slogan" id="pcb-slogan" hidden></div>' +
		'<div class="sub" id="pcb-stand">Lade …</div></div></div>' +
		'<div class="actions">' +
		'<span class="userchip">👤 ' + this.esc(frappe.session.user_fullname || frappe.session.user) + '</span>' +
		'<button class="btn primary" id="pcb-refresh" type="button">⟳ Live aktualisieren</button>' +
		'<button class="btn ghost" id="pcb-diagnose" type="button">🩺 Diagnose</button>' +
		'<button class="btn ghost" id="pcb-theme" type="button">◐ Theme</button>' +
		'</div></div>' +
		'<div class="tabs">' +
		'<button class="active" data-tab="mail">📥 Posteingang</button>' +
		'<button data-tab="wareneingang">📥 Wareneingang</button>' +
		'<button data-tab="produktion">🏭 Produktion</button>' +
		'<button data-tab="warenausgang">📦 Warenausgang</button>' +
		'<button data-tab="guv">📊 GuV</button>' +
		'<button data-tab="crm">🤝 CRM</button>' +
		'<button data-tab="assign">👤 Zuweisungen</button>' +
		'</div>' +
		'<div class="tab-panel active" id="pcb-tab-mail"><p class="muted">Lade Daten …</p></div>' +
		'<div class="tab-panel" id="pcb-tab-wareneingang"></div>' +
		'<div class="tab-panel" id="pcb-tab-produktion"></div>' +
		'<div class="tab-panel" id="pcb-tab-warenausgang"></div>' +
		'<div class="tab-panel" id="pcb-tab-guv"></div>' +
		'<div class="tab-panel" id="pcb-tab-crm"></div>' +
		'<div class="tab-panel" id="pcb-tab-assign"><p class="muted">Lade Daten …</p></div>' +
		'<p class="foot">Nur Vorschläge — es wird nichts automatisch gesendet oder gebucht. ' +
		'Alle Beträge netto.</p>' +
		'<div class="overlay" id="pcb-overlay">' + this.pcbLogoSvg(28, true, '') +
		'<div class="ov-text-wrap"><div class="ov-txt">Aktualisiere Daten …</div>' +
		'<div class="ov-sub" id="pcb-ov-sub">Outlook &amp; ERPNext werden neu ausgewertet</div></div></div>' +
		'<div class="toast" id="pcb-toast"></div>' +
		'</div>'
	);
};

// ----------------------------------------------------------------- Loading

PCBBoard.prototype.load = function () {
	var self = this;
	frappe.call({ method: 'pcb_board.api.get_board_metrics' }).then(function (r) {
		var msg = r.message || {};
		self.outlookConnected = !!(msg.metrics && msg.metrics.outlook_connected);
		if (msg.metrics && msg.metrics.dashboard_title) {
			self.$root.find('#pcb-h1').text(msg.metrics.dashboard_title);
		}
		if (msg.metrics && msg.metrics.slogan) {
			self.$root.find('#pcb-slogan').text(msg.metrics.slogan).prop('hidden', false);
		}
		if (!msg.metrics) {
			self.$root.find('#pcb-tab-mail').html(
				'<p class="muted">Noch kein Datenstand vorhanden. Auf „Live aktualisieren" klicken, ' +
					'um den ersten Abruf zu starten.</p>'
			);
			return;
		}
		self.metrics = msg.metrics;
		self.renderAll();
	});
	frappe.call({ method: 'pcb_board.api.list_assignments' }).then(function (r) {
		self.assignments = r.message || [];
		self.renderAssignTab();
	});
};

PCBBoard.prototype.pollStatus = function () {
	var self = this;
	frappe.call({ method: 'pcb_board.api.get_refresh_status' }).then(function (r) {
		var s = r.message || {};
		if (s.state === 'running') {
			self.$overlay.addClass('show');
			self.$root.find('#pcb-ov-sub').text(
				(s.started_by ? 'Gestartet von ' + s.started_by + ' — ' : '') +
					'Outlook & ERPNext werden neu ausgewertet'
			);
		} else {
			self.$overlay.removeClass('show');
			var current = self.metrics && self.metrics.generated_at;
			if (s.generated_at && s.generated_at !== current) {
				self.load();
			} else if (self.metrics) {
				self.$root.find('#pcb-stand').text(
					'Stand ' + frappe.datetime.str_to_user(self.metrics.generated_at || '') +
					(self.metrics.refresh_seconds ? ' (' + self.metrics.refresh_seconds + ' s)' : '') +
					' · nächster Refresh in ' + self.nextRefreshIn()
				);
			}
		}
	});
};

PCBBoard.prototype.handleUrlParams = function () {
	var params = frappe.utils.get_url_arg ? null : null;
	var qs = new URLSearchParams(window.location.search);
	if (qs.get('connected') === '1') {
		this.toast('Postfach verbunden ✓');
	} else if (qs.get('connect_error') === '1') {
		this.toast('Verbindung mit Outlook fehlgeschlagen — bitte erneut versuchen');
	}
};

// ----------------------------------------------------------------- Actions

PCBBoard.prototype.bindStatic = function () {
	var self = this;
	this.$root.find('#pcb-theme').on('click', function () {
		self.$root.find('.pcb-root').toggleClass('pcb-dark');
	});
	this.$root.find('.tabs button').on('click', function () {
		self.$root.find('.tabs button').removeClass('active');
		$(this).addClass('active');
		var tab = $(this).data('tab');
		self.$root.find('.tab-panel').removeClass('active');
		self.$root.find('#pcb-tab-' + tab).addClass('active');
	});
	this.$root.find('#pcb-refresh').on('click', function () {
		self.$overlay.addClass('show');
		frappe.call({ method: 'pcb_board.api.start_refresh', type: 'POST' });
	});
	this.$root.find('#pcb-diagnose').on('click', function () {
		self.showDiagnose();
	});
};

PCBBoard.prototype.showDiagnose = function () {
	var self = this;
	frappe.call({ method: 'pcb_board.api.get_config_status' }).then(function (r) {
		var s = r.message || {};
		var ok = function (v) {
			return v ? '✅' : '❌';
		};
		var rows = [
			[ok(s.azure_client_id), 'azure_client_id (Site Config)'],
			[ok(s.azure_client_secret), 'azure_client_secret (Site Config)'],
			[ok(s.azure_tenant_id), 'azure_tenant_id (Site Config)'],
			[ok(s.anthropic_api_key), 'anthropic_api_key (Site Config, sonst Keyword-Fallback)'],
			[ok(s.ups_client_id), 'ups_client_id (Site Config, sonst Fallback-Schätzung)'],
			[ok(s.ups_client_secret), 'ups_client_secret (Site Config, sonst Fallback-Schätzung)'],
			[ok(s.revenue_target), 'Umsatzziel gesetzt (PCB Board Settings)'],
			[ok(s.extra_mailboxes), 'Geteilte Postfächer gesetzt (PCB Board Settings)'],
			[ok(s.own_mailbox_connected), 'Mein Postfach verbunden (' + self.esc(frappe.session.user) + ')'],
		];
		var html =
			'<table class="pcb-diag"><tbody>' +
			rows.map(function (row) {
				return '<tr><td>' + row[0] + '</td><td>' + row[1] + '</td></tr>';
			}).join('') +
			'</tbody></table>' +
			'<p class="muted" style="margin-top:10px">Installierter Code-Stand: <code>' +
			self.esc(s.build_time || '?') + '</code> (Commit <code>' +
			self.esc((s.build_commit || '').slice(0, 12)) + '</code>)</p>' +
			'<p class="muted" style="margin-top:10px">Redirect-URI für die Azure-App-Registrierung:<br>' +
			'<code>' + self.esc(s.redirect_uri) + '</code></p>';
		frappe.msgprint({
			title: 'Konfiguration prüfen',
			message: html,
			indicator: 'blue',
		});
	});
};

PCBBoard.prototype.openAssignDialog = function (item) {
	var self = this;
	frappe.prompt(
		[{ fieldname: 'assigned_to', fieldtype: 'Link', options: 'User', label: 'Zuweisen an', reqd: 1 }],
		function (values) {
			frappe.call({
				method: 'pcb_board.api.assign_mail',
				type: 'POST',
				args: {
					internet_message_id: item.internet_message_id,
					mailbox: item.mailbox,
					sender_name: item.sender_name,
					sender: item.sender,
					subject: item.subject,
					assigned_to: values.assigned_to,
				},
			}).then(function () {
				self.toast('Zugewiesen ✓');
				self.load();
			});
		},
		'Mail zuweisen',
		'Zuweisen'
	);
};

PCBBoard.prototype.renderAssignTab = function () {
	var self = this;
	var rows = (self.assignments || []).map(function (a) {
		return '<tr><td>' + self.esc(self.shortBox(a.mailbox)) + '</td>' +
			'<td>' + self.esc(a.sender_name || a.sender || '') + '</td>' +
			'<td>' + self.esc(a.subject || '') + '</td>' +
			'<td>' + self.esc(a.assigned_to) + '</td>' +
			'<td>' + self.esc(a.status) + '</td>' +
			'<td><button class="btn ghost small" data-mid="' + self.esc(a.internet_message_id) +
			'" data-action="done">Erledigt</button> ' +
			'<button class="btn ghost small" data-mid="' + self.esc(a.internet_message_id) +
			'" data-action="remove">Entfernen</button></td></tr>';
	}).join('');
	var body = rows
		? '<table class="tbl"><thead><tr><th>Postfach</th><th>Von</th><th>Betreff</th>' +
			'<th>Zugewiesen an</th><th>Status</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>'
		: '<p class="muted">Keine Zuweisungen.</p>';
	this.$root.find('#pcb-tab-assign').html(
		'<section class="card"><div class="sec-h"><h2>Zuweisungen</h2>' +
		'<span class="muted">wer bearbeitet was — für alle sichtbar</span></div>' + body + '</section>'
	);
	this.bindAssignTabInteractions();
};

PCBBoard.prototype.bindAssignTabInteractions = function () {
	var self = this;
	this.$root.find('#pcb-tab-assign [data-action="done"]').on('click', function () {
		var mid = $(this).data('mid');
		frappe.call({
			method: 'pcb_board.api.set_assignment_status',
			type: 'POST',
			args: { internet_message_id: mid, status: 'Erledigt' },
		}).then(function () {
			self.load();
		});
	});
	this.$root.find('#pcb-tab-assign [data-action="remove"]').on('click', function () {
		var mid = $(this).data('mid');
		frappe.call({
			method: 'pcb_board.api.unassign_mail',
			type: 'POST',
			args: { internet_message_id: mid },
		}).then(function () {
			self.load();
		});
	});
};

PCBBoard.prototype.connectOutlook = function () {
	frappe.call({ method: 'pcb_board.api.connect_outlook' }).then(function (r) {
		if (r.message && r.message.url) {
			window.location.href = r.message.url;
		}
	});
};

PCBBoard.prototype.disconnectOutlook = function () {
	var self = this;
	frappe.call({ method: 'pcb_board.api.disconnect_outlook', type: 'POST' }).then(function () {
		self.toast('Postfach getrennt');
		self.load();
	});
};

// -------------------------------------------------------------------- Render

PCBBoard.prototype.renderAll = function () {
	var m = this.metrics;
	// Ein Hintergrund-Refresh baut die Reiter neu auf. Wer gerade in einem Suchfeld
	// tippt, verlöre dabei Fokus und Cursorposition — beides wird deshalb über den
	// Neuaufbau hinweg gemerkt und danach wiederhergestellt.
	var keep = this.captureFocus();
	var stand = m.generated_at ? frappe.datetime.str_to_user(m.generated_at) : '—';
	var duration = m.refresh_seconds ? ' (' + m.refresh_seconds + ' s)' : '';
	var next = ' · nächster Refresh in ' + this.nextRefreshIn();
	this.$root.find('#pcb-stand').text('Stand ' + stand + duration + next);
	this.$root.find('#pcb-tab-mail').html(this.mailTabHtml(m));
	this.$root.find('#pcb-tab-wareneingang').html(this.wareneingangTabHtml(m));
	this.$root.find('#pcb-tab-produktion').html(this.productionOrdersHtml(m));
	this.$root.find('#pcb-tab-warenausgang').html(this.warenausgangTabHtml(m));
	this.$root.find('#pcb-tab-guv').html(this.guvTabHtml(m));
	this.$root.find('#pcb-tab-crm').html(this.crmTabHtml(m));
	this.bindMailInteractions();
	this.bindWarenInteractions();
	this.restoreFocus(keep);
};

// Fokus + Cursorposition eines Eingabefeldes merken bzw. zurücksetzen.
PCBBoard.prototype.captureFocus = function () {
	var el = document.activeElement;
	if (!el || !el.id || !this.$root.find('#' + el.id).length) {
		return null;
	}
	return { id: el.id, start: el.selectionStart, end: el.selectionEnd };
};

PCBBoard.prototype.restoreFocus = function (keep) {
	if (!keep) {
		return;
	}
	var el = document.getElementById(keep.id);
	if (!el) {
		return;
	}
	el.focus();
	if (keep.start != null && el.setSelectionRange) {
		// Manche Feldtypen (u. a. type="search" in Safari) verweigern
		// setSelectionRange — der Fokus allein ist dann schon der Gewinn.
		try {
			el.setSelectionRange(keep.start, keep.end);
		} catch (e) {
			/* egal */
		}
	}
};

// Wareneingang = was hereinkommt: Bestellungen mit erwartetem Termin. Die
// Fertigungsaufträge stehen im eigenen Reiter „Produktion".
PCBBoard.prototype.wareneingangTabHtml = function (m) {
	return this.purchaseOrdersHtml(m) + this.recentReceiptsHtml(m);
};

// Warenausgang = was hinausgeht: Liefertermine der Kundenaufträge und die
// Lieferscheine, die noch abzurechnen sind.
PCBBoard.prototype.warenausgangTabHtml = function (m) {
	return this.deliveryDatesHtml(m) + this.outgoingPackagesHtml(m);
};

// GuV = frühere Tabs „Umsatz" + „Kosten".
PCBBoard.prototype.guvTabHtml = function (m) {
	return this.revenueTabHtml(m) + this.costsTabHtml(m);
};

// Materialstand eines Produktionsauftrags als Symbol + Klartext:
// ✅ vollständig · 🚚 im Zulauf (mit Termin) · ⛔ nicht bestellt.
PCBBoard.prototype.woMaterialState = function (w) {
	if (w.material_ok) {
		return { icon: '✅', text: 'Material vollständig', color: 'var(--good)' };
	}
	// Liefertermin-Liste liefert missing_count, die Auftragsliste missing_items.
	var missing = w.missing_count != null ? w.missing_count : (w.missing_items || []).length;
	if (missing) {
		return {
			icon: '⛔',
			text: missing + ' Artikel nicht bestellt',
			color: 'var(--critical)',
		};
	}
	return {
		icon: '🚚',
		text: w.complete_on
			? 'komplett ab ' + frappe.datetime.str_to_user(w.complete_on)
			: 'im Zulauf',
		color: 'var(--series-3)',
	};
};

// Spalte „Produktionsauftrag" in der Liefertermin-Liste.
PCBBoard.prototype.soWorkOrdersCell = function (r) {
	var self = this;
	var wos = r.work_orders || [];
	if (!wos.length) {
		return '<span class="muted" title="Kein Produktionsauftrag verknüpft — z. B. Handelsware">—</span>';
	}
	return '<span class="wo-list">' + wos.map(function (w) {
		var st = self.woMaterialState(w);
		var waiting = (w.awaiting || []).map(function (a) {
			return (a.supplier || a.po) + (a.expected_date
				? ' bis ' + frappe.datetime.str_to_user(a.expected_date) : '');
		}).join(', ');
		var title = (w.item_code ? w.item_code + ' · ' : '') +
			(w.on_hold ? 'Bearbeitung gesperrt · ' : '') + st.text +
			(waiting ? ' — warten auf: ' + waiting : '');
		return '<span class="wo-chip' + (w.on_hold ? ' held' : '') + '" title="' +
			self.esc(title) + '">' + self.woLink(w.name) +
			(w.on_hold ? ' <span title="Bearbeitung gesperrt">⏸</span>' : '') +
			' <span style="color:' + st.color + '">' + st.icon + '</span></span>';
	}).join(' ') + '</span>';
};

// CRM = Angebote (offen, nachzufassen, Trefferquote) + Kundenentwicklung aus den
// Rechnungsdaten + Leads/Opportunities. Alles lesend, nichts wird hier gepflegt.
PCBBoard.prototype.quoteLink = function (name) {
	return '<a href="/app/quotation/' + encodeURIComponent(name) + '" target="_blank">' +
		this.esc(name) + '</a>';
};

PCBBoard.prototype.crmTabHtml = function (m) {
	var self = this;
	if (!m.crm) {
		return '<section class="card"><div class="sec-h"><h2>🤝 CRM</h2></div>' +
			'<p class="muted">Die CRM-Daten kommen mit dem nächsten Datenabruf — ' +
			'auf „⟳ Live aktualisieren" klicken.</p></section>';
	}
	var q = m.crm.quotations || {};
	var c = m.crm.customers || {};
	var l = m.crm.leads || {};
	var o = m.crm.opportunities || {};
	var conv = q.conversion || {};
	var convPrev = q.conversion_prev || {};

	// --- Kachelzeile: der Zustand der Verkaufs-Pipeline auf einen Blick --------
	var rateTxt = conv.rate == null ? '—' : self.pct(conv.rate);
	var rateDelta = '';
	if (conv.rate != null && convPrev.rate != null) {
		var d = conv.rate - convPrev.rate;
		var up = d >= 0;
		rateDelta = ' <span style="color:' + (up ? 'var(--good)' : 'var(--critical)') +
			';font-weight:650">' + (up ? '▲ +' : '▼ −') + Math.abs(Math.round(d * 100)) +
			' %-Pkt.</span>';
	}
	var tiles =
		'<div class="tiles" style="margin-bottom:12px">' +
		'<div class="tile hero"><p class="k">Offene Angebote (netto)</p>' +
		'<div class="v">' + self.eur(q.open_net) + '</div>' +
		'<div class="m">' + (q.open_count || 0) + ' Angebot(e) beim Kunden' +
		(q.draft_count ? ' · ' + q.draft_count + ' Entwurf/Entwürfe noch nicht raus' : '') +
		'</div></div>' +
		'<div class="tile"><p class="k">Nachfassen (läuft ab ≤ ' + (q.expiring_days || 14) + ' Tage)</p>' +
		'<div class="v" style="color:' + (q.expiring_count ? 'var(--critical)' : 'var(--good)') + '">' +
		(q.expiring_count || 0) + '</div>' +
		'<div class="m">' + (q.expiring_count
			? self.eur(q.expiring_net) + ' · davon ' + (q.overdue_count || 0) + ' bereits abgelaufen'
			: 'kein Angebot läuft demnächst ab') + '</div></div>' +
		'<div class="tile"><p class="k">Trefferquote ' + self.esc(String(conv.year || '')) + '</p>' +
		'<div class="v">' + rateTxt + '</div>' +
		'<div class="m">' + (conv.decided || 0) + ' entschieden: ' + (conv.won || 0) + ' gewonnen, ' +
		(conv.lost || 0) + ' verloren, ' + (conv.expired || 0) + ' abgelaufen' + rateDelta + '</div></div>' +
		'<div class="tile"><p class="k">Neu- &amp; reaktivierte Kunden</p>' +
		'<div class="v" style="color:var(--good)">' + (c.new_count || 0) + '</div>' +
		'<div class="m">Umsatz ' + self.esc((m.as_of || '').slice(0, 4)) + ', kein Umsatz im Vorjahr</div></div>' +
		'<div class="tile"><p class="k">Schlafende Kunden</p>' +
		'<div class="v" style="color:' + (c.dormant_count ? 'var(--warning)' : 'var(--good)') + '">' +
		(c.dormant_count || 0) + '</div>' +
		'<div class="m">Vorjahresumsatz, aber seit &gt; ' + (c.dormant_days || 180) +
		' Tagen keine Rechnung</div></div>' +
		'<div class="tile"><p class="k">Leads &amp; Opportunities</p>' +
		'<div class="v">' + (l.open_count || 0) + ' / ' + (o.open_count || 0) + '</div>' +
		'<div class="m">offene Leads / offene Opportunities' +
		(o.open_amount ? ' (' + self.eur(o.open_amount) + ')' : '') + '</div></div>' +
		'</div>';

	// --- Angebote nachfassen -------------------------------------------------
	var follow = (q.open || []).filter(function (r) { return r.expiring; });
	var followBody = follow.map(function (r) {
		var badge = r.overdue
			? '<span class="dot-hi">' + Math.abs(r.days_left) + ' Tag(e) abgelaufen</span>'
			: (r.days_left === 0
				? '<span class="dot-hi">läuft heute ab</span>'
				: '<span class="pill info">' + r.days_left + ' Tag(e) gültig</span>');
		return '<tr class="late"><td>' + self.quoteLink(r.name) + '</td>' +
			'<td>' + self.esc(r.customer) + '</td>' +
			'<td>' + (r.date ? self.esc(frappe.datetime.str_to_user(r.date)) : '—') + '</td>' +
			'<td class="exp">' + (r.valid_till
				? self.esc(frappe.datetime.str_to_user(r.valid_till)) : '—') + '</td>' +
			'<td>' + badge + '</td>' +
			'<td class="num">' + (r.age_days != null ? r.age_days + ' T.' : '—') + '</td>' +
			'<td class="num">' + self.eur(r.net_total) + '</td></tr>';
	}).join('');
	var followCard = '<section class="card"><div class="sec-h"><h2>📣 Angebote nachfassen</h2>' +
		'<span class="muted">Gültigkeit läuft aus oder ist vorbei — der Kunde hat noch nicht entschieden</span></div>' +
		(follow.length
			? '<table class="tbl"><thead><tr><th>Angebot</th><th>Kunde</th><th>Datum</th>' +
				'<th>Gültig bis</th><th>Status</th><th class="num">Alter</th>' +
				'<th class="num">Netto</th></tr></thead><tbody>' + followBody +
				'</tbody><tfoot><tr><td colspan="6">Summe (' + follow.length + ')</td>' +
				'<td class="num">' + self.eur(q.expiring_net) + '</td></tr></tfoot></table>'
			: '<p class="muted">Kein Angebot läuft demnächst ab. ✅</p>') + '</section>';

	// --- Alle offenen Angebote ----------------------------------------------
	var openBody = (q.open || []).map(function (r) {
		return '<tr' + (r.overdue ? ' class="late"' : '') + '><td>' + self.quoteLink(r.name) + '</td>' +
			'<td>' + self.esc(r.customer) + '</td>' +
			'<td>' + (r.date ? self.esc(frappe.datetime.str_to_user(r.date)) : '—') + '</td>' +
			'<td class="exp">' + (r.valid_till
				? self.esc(frappe.datetime.str_to_user(r.valid_till)) : '<span class="muted">ohne Frist</span>') + '</td>' +
			'<td>' + self.esc(r.status || '') + '</td>' +
			'<td class="num">' + self.eur(r.net_total) + '</td></tr>';
	}).join('');
	var openCard = '<section class="card"><figcaption>Offene Angebote (' + (q.open_count || 0) +
		', ' + self.eur(q.open_net) + ') — nach Gültigkeit</figcaption>' +
		((q.open || []).length
			? '<table class="tbl"><thead><tr><th>Angebot</th><th>Kunde</th><th>Datum</th>' +
				'<th>Gültig bis</th><th>Status</th><th class="num">Netto</th></tr></thead>' +
				'<tbody>' + openBody + '</tbody></table>'
			: '<p class="muted">Keine offenen Angebote.</p>') + '</section>';

	// --- Angebotsbestand je Kunde (Klumpenrisiko) ---------------------------
	var custBody = (q.by_customer || []).map(function (r, idx) {
		var share = q.open_net > 0 ? r.net / q.open_net : 0;
		return '<tr><td>' + (idx + 1) + '</td><td>' + self.esc(r.customer) + '</td>' +
			'<td class="num">' + r.count + '</td>' +
			'<td class="num">' + self.eur(r.net) + '</td>' +
			'<td class="num">' + self.pct(share) + '</td></tr>';
	}).join('');
	var byCustCard = (q.by_customer || []).length
		? '<section class="card"><figcaption>Offener Angebotsbestand je Kunde (Top 5) ' +
			'<i class="muted" style="font-size:.78rem;font-weight:400">— Klumpenrisiko im Angebotsbuch</i>' +
			'</figcaption><table class="tbl"><thead><tr><th>#</th><th>Kunde</th>' +
			'<th class="num">Angebote</th><th class="num">Netto</th><th class="num">Anteil</th>' +
			'</tr></thead><tbody>' + custBody + '</tbody></table></section>'
		: '';

	// --- Trefferquote im Jahresvergleich ------------------------------------
	function convRow(x) {
		if (!x || !x.year) return '';
		return '<tr><td>' + self.esc(String(x.year)) + '</td>' +
			'<td class="num">' + (x.won || 0) + '</td>' +
			'<td class="num">' + self.eur(x.won_net) + '</td>' +
			'<td class="num">' + (x.lost || 0) + '</td>' +
			'<td class="num">' + self.eur(x.lost_net) + '</td>' +
			'<td class="num">' + (x.expired || 0) + '</td>' +
			'<td class="num">' + (x.open || 0) + '</td>' +
			'<td class="num"><b>' + (x.rate == null ? '—' : self.pct(x.rate)) + '</b></td>' +
			'<td class="num">' + (x.rate_net == null ? '—' : self.pct(x.rate_net)) + '</td></tr>';
	}
	var convCard = '<section class="card"><figcaption>Trefferquote Angebote — Jahresvergleich</figcaption>' +
		'<table class="tbl"><thead><tr><th>Jahr</th><th class="num">gewonnen</th>' +
		'<th class="num">Wert gewonnen</th><th class="num">verloren</th><th class="num">Wert verloren</th>' +
		'<th class="num">abgelaufen</th><th class="num">noch offen</th>' +
		'<th class="num">Quote (Anzahl)</th><th class="num">Quote (Wert)</th></tr></thead><tbody>' +
		convRow(conv) + convRow(convPrev) + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Quote = gewonnen ÷ entschiedene ' +
		'Angebote (gewonnen + verloren + abgelaufen). Noch offene Angebote zählen bewusst nicht ' +
		'mit — sie sind weder gewonnen noch verloren und würden die Quote künstlich drücken. ' +
		'Teilweise beauftragte Angebote gelten als gewonnen; Stornos bleiben außen vor.</p></section>';

	// --- Kundenentwicklung ---------------------------------------------------
	var newBody = (c.new || []).map(function (r) {
		return '<tr><td>' + self.esc(r.customer) + '</td>' +
			'<td>' + self.esc(frappe.datetime.str_to_user(r.first_date)) + '</td>' +
			'<td class="num">' + self.eur(r.revenue_year) + '</td></tr>';
	}).join('');
	var newCard = (c.new || []).length
		? '<section class="card"><figcaption>Neu- &amp; reaktivierte Kunden ' +
			self.esc((m.as_of || '').slice(0, 4)) + ' (' + (c.new_count || 0) + ')</figcaption>' +
			'<table class="tbl"><thead><tr><th>Kunde</th><th>erste Rechnung</th>' +
			'<th class="num">Umsatz</th></tr></thead><tbody>' + newBody + '</tbody></table>' +
			'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Umsatz im laufenden Jahr, ' +
			'kein Umsatz im Vorjahr — das umfasst echte Neukunden und zurückgewonnene Altkunden.</p></section>'
		: '';
	var dormBody = (c.dormant || []).map(function (r) {
		return '<tr class="late"><td>' + self.esc(r.customer) + '</td>' +
			'<td>' + self.esc(frappe.datetime.str_to_user(r.last_date)) + '</td>' +
			'<td class="num">' + r.days_since + ' T.</td>' +
			'<td class="num">' + self.eur(r.revenue_prev_year) + '</td>' +
			'<td class="num">' + self.eur(r.revenue_year) + '</td></tr>';
	}).join('');
	var dormCard = (c.dormant || []).length
		? '<section class="card"><div class="sec-h"><h2>😴 Schlafende Kunden</h2>' +
			'<span class="muted">hatten Vorjahresumsatz, seit über ' + (c.dormant_days || 180) +
			' Tagen keine Rechnung — größter Vorjahresumsatz zuerst</span></div>' +
			'<table class="tbl"><thead><tr><th>Kunde</th><th>letzte Rechnung</th>' +
			'<th class="num">seit</th><th class="num">Umsatz Vorjahr</th>' +
			'<th class="num">Umsatz laufendes Jahr</th></tr></thead><tbody>' + dormBody +
			'</tbody></table></section>'
		: '';

	// --- Leads & Opportunities (dünn gepflegt, daher kompakt) ---------------
	var leadChips = (l.by_status || []).map(function (s) {
		return '<span class="wo-chip">' + self.esc(s[0]) + ' <b>' + s[1] + '</b></span>';
	}).join(' ');
	var oppBody = (o.rows || []).map(function (r) {
		return '<tr><td><a href="/app/opportunity/' + encodeURIComponent(r.name) +
			'" target="_blank">' + self.esc(r.name) + '</a></td>' +
			'<td>' + self.esc(r.customer || '') + '</td>' +
			'<td>' + self.esc(r.stage || '') + '</td>' +
			'<td>' + (r.date ? self.esc(frappe.datetime.str_to_user(r.date)) : '—') + '</td>' +
			'<td class="num">' + self.eur(r.amount) + '</td></tr>';
	}).join('');
	var leadCard = (l.total || o.total)
		? '<section class="card"><figcaption>Leads &amp; Opportunities</figcaption>' +
			'<p class="m" style="margin:0 0 8px">' + (l.total || 0) + ' Leads, davon ' +
			(l.open_count || 0) + ' offen: <span class="pi-wos">' + (leadChips || '—') + '</span></p>' +
			(oppBody
				? '<table class="tbl"><thead><tr><th>Opportunity</th><th>Kunde</th><th>Phase</th>' +
					'<th>Datum</th><th class="num">Wert</th></tr></thead><tbody>' + oppBody +
					'</tbody></table>'
				: '<p class="muted">Keine offene Opportunity.</p>') + '</section>'
		: '';

	return '<section class="card"><div class="sec-h"><h2>🤝 CRM-Überblick</h2>' +
		'<span class="muted">Angebote, Trefferquote und Kundenentwicklung</span></div>' + tiles +
		'</section>' + followCard + convCard + byCustCard + openCard + newCard + dormCard + leadCard;
};

PCBBoard.prototype.deliveryDatesHtml = function (m) {
	var self = this;
	var t = m.todo || {};
	var overdue = t.overdue || [];
	var week = t.due_this_week || [];

	function soLink(name) {
		return '<a href="/app/sales-order/' + encodeURIComponent(name) + '" target="_blank">' +
			self.esc(name) + '</a>';
	}
	// Eine gemeinsame, nach Liefertermin sortierte Liste (überfällig zuerst).
	// Neuester Termin oben: absteigend nach Liefertermin, überfällige damit unten
	// (dort steht der älteste Rückstand zuletzt).
	var rows = overdue.map(function (r) { return { r: r, kind: 'overdue' }; })
		.concat(week.map(function (r) { return { r: r, kind: 'week' }; }));
	rows.sort(function (a, z) {
		var da = a.r.delivery_date || '', dz = z.r.delivery_date || '';
		return da < dz ? 1 : (da > dz ? -1 : String(a.r.name).localeCompare(String(z.r.name)));
	});
	var body = rows.map(function (o) {
		var r = o.r;
		// Status hängt am ORIGINAL-Liefertermin, nicht an der Wiedervorlage.
		var badge;
		if (r.due_state === 'overdue') {
			badge = '<span class="dot-hi">' + r.days_overdue + ' Tag(e) überfällig</span>';
		} else if (r.due_state === 'today') {
			badge = '<span class="dot-hi">heute fällig</span>';
		} else if (r.due_state === 'later') {
			badge = '<span class="pill">Liefertermin ' +
				self.esc(frappe.datetime.str_to_user(r.delivery_date)) + '</span>';
		} else {
			badge = '<span class="pill info">diese Woche</span>';
		}
		// Steht der Auftrag nur wegen der Wiedervorlage hier, sagt das ein Zeichen
		// im Status — dafür braucht es keine eigene Spalte.
		if (r.listed_by === 'followup') {
			badge += ' <span class="fu-mark" title="Wegen Wiedervorlage ' +
				self.esc(frappe.datetime.str_to_user(r.followup_date)) + ' in der Liste">📌</span>';
		}
		// Wiedervorlage: im Auftrag gepflegt (Custom Field), hier nur angezeigt.
		var followup = r.followup_date
			? '<span class="followup" title="Wiedervorlage laut Kundenauftrag">📌 ' +
				self.esc(frappe.datetime.str_to_user(r.followup_date)) + '</span>'
			: '<span class="muted">—</span>';
		return '<tr><td>' + soLink(r.name) + '</td>' +
			'<td class="col-customer" title="' + self.esc(r.customer || '') + '">' +
			self.esc(r.customer || '') + '</td>' +
			'<td>' + followup + '</td>' +
			'<td>' + self.esc(frappe.datetime.str_to_user(r.delivery_date)) + '</td>' +
			'<td>' + badge + '</td>' +
			'<td class="col-wo">' + self.soWorkOrdersCell(r) + '</td>' +
			'<td class="num">' + self.eur(r.net_open) + '</td></tr>';
	}).join('');
	var table = rows.length
		? '<table class="tbl"><thead><tr><th>Auftrag</th><th class="col-customer">Kunde</th>' +
			'<th>Wiedervorlage</th><th>Liefertermin</th>' +
			'<th>Status</th><th class="col-wo">Produktionsauftrag</th>' +
			'<th class="num">Offen (netto)</th></tr></thead>' +
			'<tbody>' + body + '</tbody></table>' +
			'<p class="muted" style="font-size:.78rem;margin:8px 0 0">Sortiert nach Liefertermin, ' +
			'neuester zuerst. „Wiedervorlage" wird im Kundenauftrag gepflegt (Feld ' +
			'<code>Wiedervorlage</code>, auch nach Freigabe änderbar) — bei Teillieferung oder ' +
			'Verzögerung eintragen. Ist eine Wiedervorlage gesetzt, bestimmt SIE, ob der Auftrag ' +
			'hier auftaucht (📌); der Auftrag ruht bis dahin. Status und Kacheln bleiben am ' +
			'Liefertermin, damit die Zusage an den Kunden sichtbar bleibt. ' +
			'✅ hinter dem Produktionsauftrag = ' +
			'Material vollständig (Bestand reicht bzw. ist bereits umgelagert). 🚚 = Material noch im ' +
			'Zulauf, ⛔ = es fehlt Material, das noch nicht bestellt ist.</p>'
		: '<p class="muted">Nichts diese Woche oder überfällig — alles im Plan. ✅</p>';

	// Liefertreue-Analyse: Ø Verzug (Tage) + Trend vs. Vorwoche (aus KPI-Snapshot).
	var avg = t.avg_overdue_days || 0;
	var trendHtml = '';
	if (t.trend && t.trend.prev_avg_overdue_days != null) {
		var da = t.trend.delta_avg_days || 0;
		var better = da < 0;
		var arrow = da === 0 ? '▶' : (better ? '▼' : '▲');
		var color = da === 0 ? 'var(--text-secondary)' : (better ? 'var(--good)' : 'var(--critical)');
		trendHtml = ' · <span style="color:' + color + ';font-weight:650" title="Ø Verzug vor einer Woche: ' +
			self.esc(String(t.trend.prev_avg_overdue_days)) + ' Tage (Stand ' +
			self.esc(frappe.datetime.str_to_user(t.trend.prev_date)) + ')">' + arrow + ' ' +
			(da > 0 ? '+' : (da < 0 ? '−' : '±')) + Math.abs(da) + ' Tage ggü. Vorwoche</span>';
	} else {
		trendHtml = ' · <span class="muted">Vorwochen-Trend ab ~1 Woche Datenhistorie</span>';
	}
	var netTrend = '';
	if (t.trend) {
		var dn = t.trend.delta_net || 0;
		var b2 = dn < 0;
		netTrend = ' <span style="color:' + (dn === 0 ? 'var(--text-secondary)' : (b2 ? 'var(--good)' : 'var(--critical)')) +
			';font-weight:650">' + (dn === 0 ? '▶' : (b2 ? '▼' : '▲')) + ' ' +
			(dn > 0 ? '+' : (dn < 0 ? '−' : '±')) + self.eur(Math.abs(dn)) + ' ggü. Vorwoche</span>';
	}
	var reliability =
		'<div class="tiles" style="margin-bottom:12px">' +
		'<div class="tile"><p class="k">Überfällig (offen, netto)</p>' +
		'<div class="v" style="color:' + (overdue.length ? 'var(--critical)' : 'var(--good)') + '">' +
		self.eur(t.overdue_net || 0) + '</div><div class="m">' + overdue.length + ' Auftrag/Aufträge' + netTrend + '</div></div>' +
		'<div class="tile"><p class="k">Ø Verzug (überfällige Aufträge)</p>' +
		'<div class="v">' + (avg ? String(avg).replace('.', ',') + ' Tage' : '—') + '</div>' +
		'<div class="m">Liefertreue' + trendHtml + '</div></div>' +
		'<div class="tile"><p class="k">Diese Woche fällig (offen, netto)</p>' +
		'<div class="v">' + self.eur(t.due_this_week_net || 0) + '</div>' +
		'<div class="m">' + week.length + ' Auftrag/Aufträge · sollten diese Woche fertig werden</div></div>' +
		'</div>';

	return '<section class="card" id="pcb-delivery-dates"><div class="sec-h">' +
		'<h2>📅 Liefertermine: diese Woche oder überfällig</h2>' +
		'<span class="muted">Handelsware & Aufträge nicht übersehen</span></div>' +
		reliability + table + '</section>';
};

// Aktuelle Bestellungen mit erwartetem Wareneingang (Bestelldatum + Median-
// Lieferzeit des Lieferanten). Überschrittene Termine werden rot markiert.
PCBBoard.prototype.poLink = function (name) {
	return '<a href="/app/purchase-order/' + encodeURIComponent(name) + '" target="_blank">' +
		this.esc(name) + '</a>';
};

PCBBoard.prototype.poStatusBadge = function (r) {
	if (r.on_hold) {
		return '<span class="muted">pausiert (On Hold)</span>';
	}
	if (r.days_late > 0) {
		return '<span class="dot-hi">' + r.days_late + ' Tag(e) überfällig</span>';
	}
	if (r.days_until === 0) {
		return '<span class="pill rel">heute erwartet</span>';
	}
	if (r.days_until > 0) {
		return '<span class="pill info">in ' + r.days_until + ' Tag(en)</span>';
	}
	return '<span class="muted">kein Termin berechenbar</span>';
};

// Woraus der erwartete Termin stammt — sonst bleibt die Zahl eine Behauptung.
PCBBoard.prototype.leadCell = function (r) {
	if (r.expected_source === 'schedule') {
		return '<span class="muted" title="Keine Lieferzeit-Historie — Wunschtermin der Bestellung">' +
			'Wunschtermin</span>';
	}
	if (r.lead_days == null) {
		return '<span class="muted">—</span>';
	}
	var days = String(r.lead_days).replace('.', ',') + ' T.';
	if (r.expected_source === 'supplier') {
		return days + ' <span class="muted" style="font-size:.76rem" title="Median aus ' +
			r.lead_samples + ' Vorgang/Vorgängen dieses Lieferanten">(' + r.lead_samples + ')</span>';
	}
	return days + ' <span class="muted" style="font-size:.76rem" ' +
		'title="Keine Historie für diesen Lieferanten — Median über alle Lieferanten">(Ø alle)</span>';
};

// Aufgeklappte Bestellungen bleiben über einen Hintergrund-Refresh hinweg offen
// (gleiche Logik wie bei den Mail-Vorschauen).
PCBBoard.prototype.bindWarenInteractions = function () {
	var self = this;
	this.$root.find('#pcb-tab-wareneingang .po-toggle').on('click', function (e) {
		e.stopPropagation();
		var $tr = $(this).closest('tr');
		var po = $tr.data('po');
		var $detail = self.$root.find('#pcb-tab-wareneingang [data-po-detail="' + po + '"]');
		var open = !!$detail.prop('hidden');
		$detail.prop('hidden', !open);
		$(this).find('.chev').text(open ? '▴' : '▾');
		if (open) self._openPos[po] = true;
		else delete self._openPos[po];
	});

	// Produktionsauftragsliste: Filter-Chips, Suche, Sortierung, Bemerkung.
	this.$root.find('#pcb-prod .chip[data-wof]').on('click', function () {
		self.$root.find('#pcb-prod .chip[data-wof]').removeClass('active');
		$(this).addClass('active');
		self._woFilter = $(this).data('wof');
		self.renderProdTable();
	});
	this.$root.find('#pcb-wo-search').on('input', function () {
		self._woQuery = $(this).val().trim();
		self.renderProdTable();
	});
	this.bindProdTable();
};

PCBBoard.prototype.woLink = function (name) {
	return '<a href="/app/work-order/' + encodeURIComponent(name) + '" target="_blank">' +
		this.esc(name) + '</a>';
};

// Spalte „Für Fertigung": Anzahl betroffener Aufträge + Hinweis, wenn diese
// Bestellung die letzte fehlende Lieferung für mindestens einen Auftrag ist.
PCBBoard.prototype.woCell = function (r, open) {
	var n = r.work_orders_count || 0;
	if (!n) {
		return '<span class="muted">—</span>';
	}
	var unlock = (r.unblocks || []).length
		? ' <span class="pill unlock" title="Mit dieser Lieferung ist der Auftrag material-komplett: ' +
			this.esc((r.unblocks || []).join(', ')) + '">🔓 letzte Lieferung</span>'
		: '';
	return '<button class="po-toggle" type="button">' + n + ' FA <span class="chev">' +
		(open ? '▴' : '▾') + '</span></button>' + unlock;
};

// Detailzeile: je Artikel der Bestellung die Fertigungsaufträge, für die er
// gedacht ist; 🔓 markiert den Auftrag, der mit dieser Lieferung startklar wird.
PCBBoard.prototype.poDetailRow = function (r, open) {
	var self = this;
	if (!(r.work_orders_count || 0)) {
		return '';
	}
	var lines = (r.items || []).map(function (it) {
		var wos = it.work_orders || [];
		var right;
		if (!wos.length) {
			right = '<span class="muted">kein Fertigungsbedarf zugeordnet</span>';
		} else {
			right = wos.map(function (w) {
				var title = (w.item_name || '') + (w.qty ? ' · ' + String(w.qty).replace('.', ',') + ' Stk.' : '') +
					(w.status ? ' · ' + w.status : '') +
					(w.need_date ? ' · Start ' + frappe.datetime.str_to_user(w.need_date) : '');
				var tag = w.is_last
					? ' <span class="unlock-tag" title="letzte fehlende Lieferung — danach ist der Auftrag material-komplett">🔓</span>'
					: (w.still_missing
						? ' <span class="muted" title="Diesem Auftrag fehlt zusätzlich Material, das noch nicht bestellt ist">⌛</span>'
						: '');
				return '<span class="wo-chip" title="' + self.esc(title) + '">' + self.woLink(w.name) + tag +
					(w.sales_order ? ' <span class="muted">(' + self.esc(w.sales_order) + ')</span>' : '') +
					'</span>';
			}).join(' ');
		}
		return '<div class="po-item"><span class="pi-name" title="' +
			self.esc(it.item_name || '') + '">' + self.esc(it.item_code || it.item_name || '') +
			(it.open_qty != null ? ' <span class="muted">×' + String(it.open_qty).replace('.', ',') + '</span>' : '') +
			'</span><span class="pi-wos">' + right + '</span></div>';
	}).join('');
	return '<tr class="po-detail" data-po-detail="' + this.esc(r.name) + '"' + (open ? '' : ' hidden') +
		'><td colspan="9"><div class="po-items">' + lines + '</div>' +
		'<p class="muted" style="font-size:.78rem;margin:6px 0 0">🔓 = mit dieser Lieferung ist der ' +
		'Auftrag material-komplett · ⌛ = dem Auftrag fehlt zusätzlich Material, das noch nicht ' +
		'bestellt ist</p></td></tr>';
};

// Eine Tabelle, zwei Verwendungen: „im Zulauf" und „überfällig" zeigen dieselben
// Spalten, damit der Blick nicht umlernen muss.
PCBBoard.prototype.poTableHtml = function (rows, emptyText) {
	var self = this;
	if (!rows.length) {
		return '<p class="muted">' + emptyText + '</p>';
	}
	var body = rows.map(function (r) {
		var late = r.days_late > 0 && !r.on_hold;
		var open = !!self._openPos[r.name];
		return '<tr' + (late ? ' class="late"' : '') + ' data-po="' + self.esc(r.name) + '">' +
			'<td>' + self.poLink(r.name) + '</td>' +
			'<td>' + self.esc(r.supplier) + '</td>' +
			'<td>' + (r.order_date ? self.esc(frappe.datetime.str_to_user(r.order_date)) : '—') + '</td>' +
			'<td class="num">' + self.leadCell(r) + '</td>' +
			'<td class="exp">' + (r.expected_date
				? self.esc(frappe.datetime.str_to_user(r.expected_date)) : '—') + '</td>' +
			'<td class="num">' + r.positions + '</td>' +
			'<td>' + self.woCell(r, open) + '</td>' +
			'<td class="num">' + self.eur(r.net_open) + '</td>' +
			'<td>' + self.poStatusBadge(r) + '</td></tr>' +
			self.poDetailRow(r, open);
	}).join('');
	var netSum = rows.reduce(function (a, r) { return a + (r.net_open || 0); }, 0);
	var posSum = rows.reduce(function (a, r) { return a + (r.positions || 0); }, 0);
	return '<table class="tbl po-tbl"><thead><tr><th>Bestellung</th><th>Lieferant</th>' +
		'<th>Bestellt am</th><th class="num">Ø Lieferzeit</th><th>Erwartet am</th>' +
		'<th class="num">Positionen</th><th>Für Fertigung</th><th class="num">Offen (netto)</th>' +
		'<th>Status</th></tr></thead><tbody>' + body +
		'</tbody><tfoot><tr><td colspan="5">Summe (' + rows.length + ')</td>' +
		'<td class="num">' + posSum + '</td><td></td>' +
		'<td class="num">' + self.eur(netSum) + '</td><td></td></tr></tfoot></table>';
};

PCBBoard.prototype.purchaseOrdersHtml = function (m) {
	var self = this;
	// Fehlt der Block komplett, ist der gecachte Stand älter als dieses Feature —
	// dann keine leere Erfolgsmeldung zeigen, sondern auf den Refresh verweisen.
	if (!m.purchasing) {
		return '<section class="card"><div class="sec-h"><h2>🛒 Bestellungen</h2></div>' +
			'<p class="muted">Die Bestelldaten kommen mit dem nächsten Datenabruf — ' +
			'auf „⟳ Live aktualisieren" klicken.</p></section>';
	}
	var p = m.purchasing;
	var all = p.open || [];
	var et = p.expected_today || {};
	var lt = p.lead_times || {};

	// Überfällig = Termin überschritten und nicht bewusst pausiert (dieselbe
	// Auswahl, die metrics.py fürs Nachfassen bildet). Alles andere ist im Zulauf,
	// „On Hold" eingeschlossen — dort ist nichts anzumahnen.
	var lateNames = {};
	(p.follow_up || []).forEach(function (r) { lateNames[r.name] = true; });
	var incoming = all.filter(function (r) { return !lateNames[r.name]; });
	var overdue = p.follow_up || [];
	var incomingNet = incoming.reduce(function (a, r) { return a + (r.net_open || 0); }, 0);

	// Kachel „heute erwartet": Artikel stehen im Vordergrund, nicht der Betrag.
	// Gelistet wird der Item-Code, der Klartextname steckt im Tooltip.
	var names = (et.items || []).map(function (i) {
		return '<span title="' + self.esc(i.item_name || '') + '">' +
			self.esc(i.item_code || i.item_name || '') + '</span>' + (i.open_qty != null
			? ' <span class="muted">×' + String(i.open_qty).replace('.', ',') + '</span>' : '');
	});
	var namesLine = names.length
		? names.slice(0, 3).join(' · ') + (names.length > 3 ? ' · +' + (names.length - 3) + ' weitere' : '')
		: 'heute wird nichts erwartet';

	var incomingTiles =
		'<div class="tiles" style="margin-bottom:12px">' +
		'<div class="tile"><p class="k">Heute erwartete Artikel</p>' +
		'<div class="v" style="color:' + (et.positions ? 'var(--series-1)' : 'var(--text-primary)') + '">' +
		(et.positions || 0) + '</div>' +
		'<div class="m">' + (et.orders ? 'aus ' + et.orders + ' Bestellung(en) · ' + self.eur(et.net) +
			'<br>' + namesLine : namesLine) + '</div></div>' +
		'<div class="tile"><p class="k">Im Zulauf</p>' +
		'<div class="v">' + incoming.length + '</div>' +
		'<div class="m">' + self.eur(incomingNet) + ' · Termin noch nicht überschritten</div></div>' +
		'<div class="tile"><p class="k">Fertigung wartet auf Material</p>' +
		'<div class="v" style="color:' + (p.wo_waiting_count ? 'var(--warning)' : 'var(--good)') + '">' +
		(p.wo_waiting_count || 0) + '</div>' +
		'<div class="m">' + (p.wo_waiting_count
			? (p.wo_unblockable_count || 0) + ' wird durch erwartete Lieferungen komplett · ' +
				(p.wo_need_order_count || 0) + ' braucht noch Bestellungen'
			: 'kein Fertigungsauftrag wartet auf Material') + '</div></div>' +
		'<div class="tile"><p class="k">Ø Lieferzeit (alle Lieferanten)</p>' +
		'<div class="v">' + (lt.overall_median_days != null
			? String(lt.overall_median_days).replace('.', ',') + ' Tage' : '—') + '</div>' +
		'<div class="m">' + (lt.samples
			? 'Median aus ' + lt.samples + ' Vorgang/Vorgängen (Bestellung → Wareneingang)'
			: 'noch keine Bestellung mit Wareneingang verknüpft') + '</div></div>' +
		'</div>';

	var incomingCard =
		'<section class="card"><div class="sec-h"><h2>🚚 Aktuell im Zulauf</h2>' +
		'<span class="muted">Termin je Lieferant aus der eigenen Lieferzeit-Historie — ' +
		'nächster Termin oben</span></div>' + incomingTiles +
		self.poTableHtml(incoming, 'Keine Bestellung im Zulauf.') +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Erwartet am = Bestelldatum + ' +
		'Median-Lieferzeit dieses Lieferanten (Bestellung → erster Wareneingang). Ohne eigene ' +
		'Historie greift der Median über alle Lieferanten, ohne jede Historie der Wunschtermin ' +
		'der Bestellung. Bewusst pausierte Bestellungen („On Hold") stehen hier mit, weil bei ' +
		'ihnen nichts anzumahnen ist.</p></section>';

	var overdueTiles =
		'<div class="tiles" style="margin-bottom:12px">' +
		'<div class="tile"><p class="k">Überfällige Bestellungen</p>' +
		'<div class="v" style="color:' + (overdue.length ? 'var(--critical)' : 'var(--good)') + '">' +
		overdue.length + '</div>' +
		'<div class="m">' + (overdue.length
			? self.eur(p.follow_up_net) + ' · beim Lieferanten nachfassen'
			: 'alle Bestellungen im Zeitplan') + '</div></div>' +
		'<div class="tile"><p class="k">Längste Überschreitung</p>' +
		'<div class="v" style="color:' + (overdue.length ? 'var(--critical)' : 'var(--good)') + '">' +
		(overdue.length ? overdue[0].days_late + ' Tage' : '—') + '</div>' +
		'<div class="m">' + (overdue.length
			? self.esc(overdue[0].name) + ' · ' + self.esc(overdue[0].supplier || '')
			: 'kein Termin überschritten') + '</div></div>' +
		'</div>';

	var overdueCard =
		'<section class="card"><div class="sec-h"><h2>⏰ Überfällige Bestellungen</h2>' +
		'<span class="muted">erwarteter Wareneingang überschritten — längste Überschreitung oben</span>' +
		'</div>' + overdueTiles +
		self.poTableHtml(overdue, 'Keine überfällige Bestellung. ✅') + '</section>';

	return incomingCard + overdueCard;
};

// Alle Produktionsaufträge mit ihrem Materialstand. Ersetzt die frühere Rubrik
// „Nachzuhaken": überfällige Bestellungen sind in der Bestellliste rot markiert,
// hier steht die Wirkung — welcher Auftrag deshalb nicht laufen kann.
// Sortier- und filterbar; der Zustand liegt auf der Instanz, damit ein
// Hintergrund-Refresh Sortierung und Filter nicht zurücksetzt.
PCBBoard.PROD_COLS = [
	{ key: 'name', label: 'Produktionsauftrag' },
	{ key: 'item', label: 'Artikel' },
	{ key: 'qty', label: 'Menge', cls: 'num' },
	{ key: 'status', label: 'Status' },
	{ key: 'customer_due_date', label: 'Wunschtermin Kunde' },
	{ key: 'hold', label: 'Bearbeitung' },
	{ key: 'sales_order', label: 'Kundenauftrag' },
	{ key: 'material', label: 'Material' },
	{ key: 'ready', label: 'Vollständigkeit / Warten auf' },
	{ key: 'assignee', label: 'Zuständig' },
	{ key: 'note', label: 'Bemerkung' },
];

// Sortierwert je Spalte. Material sortiert nach Dringlichkeit (fehlend zuerst),
// nicht alphabetisch — sonst stünde „im Zulauf" vor „nicht bestellt".
PCBBoard.prototype.prodSortValue = function (w, key) {
	switch (key) {
		case 'item': return String(w.production_item || w.item_name || '').toLowerCase();
		case 'qty': return Number(w.qty || 0);
		case 'material': return (w.missing_items || []).length ? 0 : (w.material_ok ? 2 : 1);
		case 'hold': return w.on_hold ? 0 : 1;
		case 'ready': return w.ready_pct == null ? -1 : w.ready_pct;
		// Ohne Zuständigen nach hinten: die Zeilen brauchen jemanden.
		case 'assignee': return (w.assignee || '\uffff').toLowerCase();
		case 'note': return String(w.note_date || w.note_remark || '').toLowerCase();
		case 'customer_due_date': return w.customer_due_date || '9999-12-31';
		default: return String(w[key] == null ? '' : w[key]).toLowerCase();
	}
};

// Liegt der fehlende Artikel schon im Einkaufstool, die EKT-Nummer verlinken —
// dann muss niemand rätseln, ob der Einkauf davon weiß.
PCBBoard.prototype.ektTag = function (it) {
	if (!it.ekt) {
		return ' <span class="muted" title="Keine Anfrage im Einkaufstool gefunden">· keine EKT</span>';
	}
	var title = 'Einkaufstool-Anfrage ' + it.ekt +
		(it.ekt_created ? ' vom ' + frappe.datetime.str_to_user(it.ekt_created) : '') +
		(it.ekt_match === 'work_order'
			? ' — dieser Fertigungsauftrag ist dort ausdrücklich genannt'
			: ' — Anfrage für diesen Artikel (neueste)');
	return ' · <a class="ekt-link" href="/app/einkaufstool/' + encodeURIComponent(it.ekt) +
		'" target="_blank" title="' + this.esc(title) + '">' + this.esc(it.ekt) + '</a>';
};

// Schalter „Bearbeitung gesperrt": markiert den Auftrag nur im Board (der
// ERPNext-Beleg bleibt unberührt), damit alle sehen, dass hier gerade nichts geht.
PCBBoard.prototype.holdCell = function (w) {
	if (w.on_hold) {
		var since = w.on_hold_since
			? ' seit ' + frappe.datetime.str_to_user(w.on_hold_since) : '';
		return '<button class="hold-btn on" type="button" data-wo="' + this.esc(w.name) +
			'" data-hold="0" title="Sperre aufheben — der Auftrag ist wieder in Bearbeitung">' +
			'⏸ gesperrt' + this.esc(since) + '</button>';
	}
	return '<button class="hold-btn" type="button" data-wo="' + this.esc(w.name) +
		'" data-hold="1" title="Als aktuell zur Bearbeitung gesperrt markieren">' +
		'On Hold</button>';
};

// Spalte „Vollständigkeit / Warten auf": zugeklappt der Anteil greifbarer
// Stücklistenpositionen, aufgeklappt jede Position mit ihrem Zustand —
// grün = vorhanden, gelb = im Zulauf, rot gestrichelt = nicht bestellt. So ist
// auch sichtbar, was seit Anlage des Auftrags schon eingetroffen ist.
PCBBoard.PROD_POS_STATE = {
	done: { cls: 'ok', icon: '✅', text: 'in der Fertigung' },
	stock: { cls: 'ok', icon: '✅', text: 'am Lager' },
	incoming: { cls: 'wait', icon: '🚚', text: 'im Zulauf' },
	missing: { cls: 'missing', icon: '⛔', text: 'nicht bestellt' },
};

PCBBoard.prototype.materialCell = function (w, open) {
	var self = this;
	var total = w.positions_total || 0;
	if (!total) {
		return '<span class="muted">keine Stücklistenpositionen</span>';
	}
	var pct = w.ready_pct == null ? 0 : w.ready_pct;
	var col = pct >= 1 ? 'var(--good)' : (pct >= 0.8 ? 'var(--series-3)' : 'var(--critical)');
	var title = (w.positions_ready || 0) + ' von ' + total + ' Positionen greifbar · ' +
		(w.positions_incoming || 0) + ' im Zulauf · ' + (w.positions_missing || 0) + ' nicht bestellt' +
		(w.qty_ready_pct != null ? ' · mengengewichtet ' + self.pct(w.qty_ready_pct) : '') +
		(w.beistellung_count ? ' · ' + w.beistellung_count + ' Beistellung(en) nicht mitgezählt' : '');
	var head = '<button class="mat-toggle" type="button" data-wo="' + self.esc(w.name) +
		'" title="' + self.esc(title) + '">' +
		'<span class="mat-bar"><i style="width:' + (pct * 100).toFixed(0) + '%;background:' + col + '"></i></span>' +
		'<b style="color:' + col + '">zu ' + self.pct(pct) + ' vollständig</b>' +
		' <span class="muted">(' + (w.positions_ready || 0) + '/' + total + ')</span>' +
		' <span class="chev">' + (open ? '▴' : '▾') + '</span></button>';

	// Reihenfolge: erst die Lücken, dann der Zulauf, dann das Vorhandene —
	// oben steht, was Arbeit macht.
	var order = { missing: 0, incoming: 1, stock: 2, done: 3 };
	var rows = (w.positions || []).slice().sort(function (a, z) {
		var d = order[a.state] - order[z.state];
		return d !== 0 ? d : String(a.item_code).localeCompare(String(z.item_code));
	});
	var list = rows.map(function (p) {
		var st = PCBBoard.PROD_POS_STATE[p.state] || PCBBoard.PROD_POS_STATE.missing;
		var detail;
		if (p.state === 'missing') {
			detail = 'fehlen ' + String(p.short_qty).replace('.', ',') + ' Stk.' +
				self.ektTag({ ekt: p.ekt });
		} else if (p.state === 'incoming') {
			detail = (p.incoming || []).map(function (i) {
				return '<b>' + self.esc(i.supplier || '?') + '</b> ' + self.poLink(i.po) +
					(i.expected_date
						? ' <span class="muted">' + self.esc(frappe.datetime.str_to_user(i.expected_date)) +
							'</span>' : '') +
					(i.is_last ? ' <span title="letzte fehlende Lieferung für diesen Auftrag">🔓</span>' : '');
			}).join(' · ');
		} else if (p.state === 'stock') {
			detail = '<span class="muted">am Lager verfügbar</span>';
		} else {
			detail = '<span class="muted">bereits umgelagert</span>';
		}
		return '<div class="mat-pos ' + st.cls + '" title="' + self.esc(p.item_name || '') + '">' +
			'<span class="mp-code">' + st.icon + ' ' + self.esc(p.item_code) + '</span>' +
			'<span class="mp-qty">' + String(p.required_qty).replace('.', ',') + ' Stk.</span>' +
			'<span class="mp-info">' + detail + '</span></div>';
	}).join('');

	return head + '<div class="mat-detail"' + (open ? '' : ' hidden') + '>' + list + '</div>';
};

PCBBoard.prototype.prodRows = function (m) {
	var self = this;
	var rows = (((m || this.metrics || {}).purchasing || {}).work_orders || []).slice();
	var f = this._woFilter || 'all';
	var q = (this._woQuery || '').toLowerCase();
	rows = rows.filter(function (w) {
		var missing = (w.missing_items || []).length;
		if (f === 'held' && !w.on_hold) return false;
		if (f === 'missing' && !missing) return false;
		if (f === 'incoming' && (missing || w.material_ok)) return false;
		if (f === 'ok' && !w.material_ok) return false;
		if (!q) return true;
		var hay = [w.name, w.production_item, w.item_name, w.sales_order, w.status, w.note_remark,
			w.assignee, (w.on_hold ? 'gesperrt on hold' : '')]
			.concat((w.awaiting || []).map(function (a) {
				return [a.supplier, a.po].concat((a.items || []).map(function (i) { return i.item_code; })).join(' ');
			}))
			.concat((w.missing_items || []).map(function (i) {
				return [i.item_code, i.item_name, i.ekt].join(' ');
			}))
			.join(' ').toLowerCase();
		return hay.indexOf(q) >= 0;
	});
	var sort = this._woSort || { key: 'customer_due_date', dir: 1 };
	rows.sort(function (a, z) {
		var va = self.prodSortValue(a, sort.key), vz = self.prodSortValue(z, sort.key);
		if (va < vz) return -sort.dir;
		if (va > vz) return sort.dir;
		return String(a.name).localeCompare(String(z.name));
	});
	return rows;
};

PCBBoard.prototype.prodTableHtml = function (m) {
	var self = this;
	var rows = this.prodRows(m);
	var sort = this._woSort || { key: 'customer_due_date', dir: 1 };
	var head = PCBBoard.PROD_COLS.map(function (c) {
		if (c.nosort) {
			return '<th' + (c.cls ? ' class="' + c.cls + '"' : '') + '>' + self.esc(c.label) + '</th>';
		}
		var active = sort.key === c.key;
		return '<th class="sortable' + (c.cls ? ' ' + c.cls : '') + (active ? ' sorted' : '') +
			'" data-sort="' + c.key + '" title="Nach dieser Spalte sortieren">' + self.esc(c.label) +
			'<span class="sort-ind">' + (active ? (sort.dir > 0 ? '▲' : '▼') : '⇅') + '</span></th>';
	}).join('');

	if (!rows.length) {
		return '<table class="tbl prod-tbl"><thead><tr>' + head + '</tr></thead><tbody>' +
			'<tr><td colspan="' + PCBBoard.PROD_COLS.length + '" class="muted">' +
			'Kein Produktionsauftrag passt zu Filter/Suche.</td></tr></tbody></table>';
	}

	var body = rows.map(function (w) {
		var st = self.woMaterialState(w);
		var matTitle = st.text + (w.beistellung_count
			? ' · ' + w.beistellung_count + ' Beistellung(en) nicht mitgezählt' : '');
		var waitCell = self.materialCell(w, !!self._openWos[w.name]);
		var note = '';
		if (w.note_date) {
			note += '<span class="note-date" title="vom Team korrigierter Liefertermin">📅 ' +
				self.esc(frappe.datetime.str_to_user(w.note_date)) + '</span>';
		}
		if (w.note_remark) {
			note += (note ? ' ' : '') + '<span class="note-txt">' + self.esc(w.note_remark) + '</span>';
		}
		// Gesperrte Aufträge treten optisch zurück; die rote Materialwarnung soll
		// bei ihnen nicht mehr um Aufmerksamkeit buhlen.
		var rowCls = w.on_hold ? ' class="held"' : ((w.missing_items || []).length ? ' class="late"' : '');
		return '<tr' + rowCls + '>' +
			'<td>' + self.woLink(w.name) + '</td>' +
			'<td title="' + self.esc(w.item_name || '') + '">' +
			self.esc(w.production_item || w.item_name || '') + '</td>' +
			'<td class="num">' + (w.qty != null ? String(w.qty).replace('.', ',') : '—') + '</td>' +
			'<td>' + self.esc(w.status || '') + '</td>' +
			'<td>' + (w.customer_due_date
				? self.esc(frappe.datetime.str_to_user(w.customer_due_date))
				: '<span class="muted" title="Kein Liefertermin an der AB hinterlegt">—</span>') + '</td>' +
			'<td class="hold-cell">' + self.holdCell(w) + '</td>' +
			'<td>' + (w.sales_order
				? '<a href="/app/sales-order/' + encodeURIComponent(w.sales_order) + '" target="_blank">' +
					self.esc(w.sales_order) + '</a>'
				: '<span class="muted">—</span>') + '</td>' +
			'<td><span style="color:' + st.color + ';font-weight:650" title="' + self.esc(matTitle) + '">' +
			st.icon + ' ' + self.esc(st.text) + '</span></td>' +
			'<td>' + waitCell + '</td>' +
			'<td class="assignee-cell"><button class="assignee-btn' + (w.assignee ? ' set' : '') +
			'" type="button" data-wo="' + self.esc(w.name) + '" title="Kürzel des Zuständigen ' +
			'eintragen oder ändern">' + (w.assignee ? self.esc(w.assignee) : '＋') + '</button></td>' +
			'<td class="note-cell"><button class="note-btn" type="button" data-wo="' + self.esc(w.name) +
			'" title="Liefertermin korrigieren / Bemerkung erfassen">' +
			(note || '<span class="muted">✎ Bemerkung</span>') + '</button></td></tr>';
	}).join('');
	return '<table class="tbl prod-tbl"><thead><tr>' + head + '</tr></thead><tbody>' + body +
		'</tbody></table>';
};

PCBBoard.prototype.productionOrdersHtml = function (m) {
	var self = this;
	if (!m.purchasing) {
		return '';
	}
	var all = (m.purchasing.work_orders || []);
	if (!all.length) {
		return '<section class="card"><div class="sec-h"><h2>🏭 Produktionsaufträge &amp; Materialstand</h2></div>' +
			'<p class="muted">Kein offener Produktionsauftrag.</p></section>';
	}
	var ok = all.filter(function (w) { return w.material_ok; }).length;
	var missing = all.filter(function (w) { return (w.missing_items || []).length; }).length;
	var incoming = all.length - ok - missing;
	var held = all.filter(function (w) { return w.on_hold; }).length;
	var f = this._woFilter || 'all';
	function chip(key, label) {
		return '<button class="chip' + (f === key ? ' active' : '') + '" data-wof="' + key + '">' +
			label + '</button>';
	}
	var controls =
		'<div class="mailctl"><div class="chips" style="margin:0">' +
		chip('all', 'Alle <span class="chip-n">' + all.length + '</span>') +
		chip('missing', '⛔ nicht bestellt <span class="chip-n">' + missing + '</span>') +
		chip('incoming', '🚚 im Zulauf <span class="chip-n">' + incoming + '</span>') +
		chip('ok', '✅ vollständig <span class="chip-n">' + ok + '</span>') +
		(held ? chip('held', '⏸ gesperrt <span class="chip-n">' + held + '</span>') : '') +
		'</div><input type="search" id="pcb-wo-search" placeholder="Suche: Auftrag, Item-Code, Lieferant, AB, Bemerkung …" ' +
		'value="' + this.esc(this._woQuery || '') + '"></div>';

	return '<section class="card" id="pcb-prod"><div class="sec-h"><h2>🏭 Produktionsaufträge &amp; Materialstand</h2>' +
		'<span class="muted">' + ok + ' vollständig · ' + incoming + ' im Zulauf · ' +
		missing + ' nicht bestellt</span></div>' + controls +
		'<div id="pcb-prod-table">' + this.prodTableHtml(m) + '</div>' +
		'<p class="muted" style="font-size:.78rem;margin:8px 0 0">Vollständigkeit = Anteil der ' +
		'Stücklistenpositionen, deren Material greifbar ist (in der Fertigung oder am Lager). ' +
		'Gezählt werden Positionen, nicht Mengen — eine Position über 5.000 Widerstände ist fürs ' +
		'Rüsten genauso eine Lücke wie die eine fehlende Platine; die mengengewichtete Quote steht ' +
		'im Tooltip. Aufklappen zeigt jede Position: grün = vorhanden, gelb = im Zulauf, rot ' +
		'gestrichelt = nicht bestellt. Materialbedarf = Sollmenge minus ' +
		'bereits umgelagerte Menge, gedeckt aus dem Bestand des Quelllagers und den erwarteten ' +
		'Wareneingängen. Als Beistellung gekennzeichnete Positionen (Kunde liefert bei) bleiben ' +
		'außen vor. Fehlt ein Artikel und ist nichts bestellt, steht die EKT-Nummer der ' +
		'passenden Einkaufstool-Anfrage daneben. Bestand und Zulauf werden nur einmal verplant: bei knapper Menge bekommt ' +
		'der Auftrag mit dem früheren Bedarfstermin den Vorrang. Spalte „Bemerkung": frei ' +
		'pflegbar, ändert nichts am ERPNext-Beleg.</p></section>';
};

// Nur die Tabelle neu zeichnen — Suchfeld behält Fokus und Cursorposition.
PCBBoard.prototype.renderProdTable = function () {
	this.$root.find('#pcb-prod-table').html(this.prodTableHtml(this.metrics));
	this.bindProdTable();
};

PCBBoard.prototype.bindProdTable = function () {
	var self = this;
	var root = this.$root.find('#pcb-prod');
	root.find('th.sortable').on('click', function () {
		var key = $(this).data('sort');
		var cur = self._woSort || { key: 'customer_due_date', dir: 1 };
		self._woSort = { key: key, dir: cur.key === key ? -cur.dir : 1 };
		self.renderProdTable();
	});
	root.find('.note-btn').on('click', function () {
		self.openWorkOrderNote($(this).data('wo'));
	});
	root.find('.assignee-btn').on('click', function () {
		self.openWorkOrderAssignee($(this).data('wo'));
	});
	root.find('.hold-btn').on('click', function () {
		self.toggleWorkOrderHold($(this).data('wo'), $(this).data('hold') ? 1 : 0);
	});
	// Positionsliste auf-/zuklappen; der Zustand überlebt Sortieren, Filtern und
	// einen Hintergrund-Refresh.
	root.find('.mat-toggle').on('click', function () {
		var wo = $(this).data('wo');
		var $detail = $(this).siblings('.mat-detail');
		var open = !!$detail.prop('hidden');
		$detail.prop('hidden', !open);
		$(this).find('.chev').text(open ? '▴' : '▾');
		if (open) self._openWos[wo] = true;
		else delete self._openWos[wo];
	});
};

// Kürzel des Zuständigen — kurzer Dialog, damit es beim Durchgehen der Liste
// schnell geht. Gespeichert wird in der Board-Notiz, nicht am ERPNext-Beleg.
PCBBoard.prototype.openWorkOrderAssignee = function (woName) {
	var self = this;
	var wo = null;
	(((this.metrics || {}).purchasing || {}).work_orders || []).forEach(function (w) {
		if (w.name === woName) wo = w;
	});
	if (!wo) return;
	frappe.prompt(
		[{ fieldname: 'assignee', fieldtype: 'Data', label: 'Zuständig (Kürzel)',
		   default: wo.assignee || '',
		   description: 'Kürzel der Person, die den Auftrag betreut. Leer lassen entfernt die Zuständigkeit.' }],
		function (values) {
			frappe.call({
				method: 'pcb_board.api.set_work_order_assignee',
				type: 'POST',
				args: { work_order: woName, assignee: values.assignee || '' },
			}).then(function (r) {
				var res = (r && r.message) || {};
				self.eachWorkOrder(woName, function (w) { w.assignee = res.assignee || null; });
				self.toast(res.assignee ? 'Zuständig: ' + res.assignee : 'Zuständigkeit entfernt');
				self.renderProdTable();
			});
		},
		'Produktionsauftrag ' + woName,
		'Speichern'
	);
};

PCBBoard.prototype.toggleWorkOrderHold = function (woName, hold) {
	var self = this;
	frappe.call({
		method: 'pcb_board.api.set_work_order_hold',
		type: 'POST',
		args: { work_order: woName, on_hold: hold },
	}).then(function (r) {
		var res = (r && r.message) || {};
		// Alle Kopien des Auftrags mitziehen (Produktionsliste UND Liefertermine),
		// damit die Markierung ohne Neuladen überall stimmt.
		self.eachWorkOrder(woName, function (w) {
			w.on_hold = !!res.on_hold;
			w.on_hold_since = res.on_hold_since || null;
		});
		self.toast(res.on_hold ? 'Auftrag gesperrt ⏸' : 'Sperre aufgehoben ▶');
		self.renderProdTable();
		// Liefertermin-Karte mitziehen: dort steht derselbe Auftrag als Kürzel.
		self.$root.find('#pcb-delivery-dates').replaceWith(self.deliveryDatesHtml(self.metrics));
	});
};

// Ein Produktionsauftrag steckt in mehreren Listen (Produktionsübersicht und je
// Kundenauftrag) — Änderungen müssen überall ankommen.
PCBBoard.prototype.eachWorkOrder = function (name, fn) {
	var m = this.metrics || {};
	((m.purchasing || {}).work_orders || []).forEach(function (w) {
		if (w.name === name) fn(w);
	});
	var todo = m.todo || {};
	['overdue', 'due_this_week'].forEach(function (g) {
		(todo[g] || []).forEach(function (so) {
			(so.work_orders || []).forEach(function (w) {
				if (w.name === name) fn(w);
			});
		});
	});
};

PCBBoard.prototype.openWorkOrderNote = function (woName) {
	var self = this;
	var wos = ((this.metrics || {}).purchasing || {}).work_orders || [];
	var wo = null;
	wos.forEach(function (w) { if (w.name === woName) wo = w; });
	if (!wo) return;
	frappe.prompt(
		[
			{ fieldname: 'revised_date', fieldtype: 'Date', label: 'Korrigierter Liefertermin',
			  default: wo.note_date || wo.customer_due_date || null,
			  description: 'Wunschtermin Kunde laut AB: ' +
				(wo.customer_due_date ? frappe.datetime.str_to_user(wo.customer_due_date) : '—') },
			{ fieldname: 'remark', fieldtype: 'Small Text', label: 'Bemerkung',
			  default: wo.note_remark || '' },
		],
		function (values) {
			frappe.call({
				method: 'pcb_board.api.set_work_order_note',
				type: 'POST',
				args: {
					work_order: woName,
					revised_date: values.revised_date || '',
					remark: values.remark || '',
				},
			}).then(function (r) {
				var res = (r && r.message) || {};
				wo.note_date = res.revised_date || null;
				wo.note_remark = res.remark || null;
				self.toast(res.revised_date || res.remark ? 'Bemerkung gespeichert ✓' : 'Bemerkung entfernt');
				self.renderProdTable();
			});
		},
		'Produktionsauftrag ' + woName,
		'Speichern'
	);
};

PCBBoard.prototype.costsTabHtml = function (m) {
	var self = this;
	var c = m.costs || {};
	var ph = m.profit_history || {};
	var carry = ph.carry_forward || 0;
	var year = (m.as_of || '').slice(0, 4);
	var rows = [
		['Wareneingänge (Monat)', c.goods_receipts, 'aus Purchase Receipt, ERPNext'],
		['Personalkosten (Monat)', c.personnel_costs, 'PCB Board Settings'],
		['Miete (Monat)', c.rent, 'PCB Board Settings'],
	];
	var tiles = '<div class="tiles">' + rows.map(function (r) {
		return '<div class="tile"><p class="k">' + self.esc(r[0]) + '</p>' +
			'<div class="v">' + self.eur(r[1]) + '</div>' +
			'<div class="m">' + self.esc(r[2]) + '</div></div>';
	}).join('') +
		'<div class="tile"><p class="k">Gesamtkosten (Monat)</p>' +
		'<div class="v" style="color:var(--critical)">' + self.eur(c.total) + '</div>' +
		'<div class="m">Wareneingänge + Personal + Miete</div></div>' +
		'<div class="tile"><p class="k">Vortrag ' + self.esc(year) + '</p>' +
		'<div class="v" style="color:' + (carry >= 0 ? 'var(--good)' : 'var(--critical)') + '">' +
		self.eur(carry) + '</div>' +
		'<div class="m">kumulierter Gewinn/Verlust der abgeschlossenen Monate</div></div>' +
		'</div>';
	return '<section class="card"><div class="sec-h"><h2>Kosten</h2>' +
		'<span class="muted">laufender Monat</span></div>' + tiles + '</section>' +
		this.topPurchasesHtml(m) + this.topSuppliersHtml(m) +
		this.topSuppliersYearHtml(m) +
		this.productMarginsHtml(m) + this.productFlopsHtml(m) +
		this.productMarginsYearHtml(m) + this.profitHistoryHtml(m);
};

PCBBoard.prototype.topSuppliersHtml = function (m) {
	var self = this;
	var items = m.top_suppliers || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (s, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td>' + self.esc(s.supplier) + '</td>' +
			'<td class="num">' + self.eur(s.net_total) + '</td>' +
			'<td class="num">' + self.pct(s.share_pct) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Lieferanten (Monat, Netto-Einkaufswert — Abhängigkeiten im Blick behalten)</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Lieferant</th><th class="num">Einkaufswert</th>' +
		'<th class="num">Anteil</th></tr></thead><tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.productMarginsHtml = function (m) {
	var self = this;
	var items = m.product_margins || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (p) {
		var c = self.dbCells(p);
		return '<tr><td title="' + self.esc(p.item_name || '') + '">' +
			self.esc(p.item_code || p.item_name) + '</td>' +
			'<td class="num">' + self.eur(p.revenue) + '</td>' +
			'<td class="num">' + self.pct(p.share_pct) + '</td>' +
			'<td class="num">' + c.cost + '</td>' +
			'<td class="num">' + c.margin + '</td>' +
			'<td class="num">' + c.marginPct + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Deckungsbeitrag Top-Produkte (Monat)</figcaption>' +
		'<table class="tbl"><thead><tr><th>Produkt</th><th class="num">Umsatz</th>' +
		'<th class="num">Anteil</th>' +
		'<th class="num">Wareneinsatz</th><th class="num">DB</th><th class="num">DB %</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Wareneinsatz = verkaufte Menge × ' +
		'letzter Einkaufspreis (EK) des Artikels; ohne EK greift der Wert der aktiven ' +
		'Standard-Stückliste je Einheit (SL). Fehlt beides, bleibt die Marge leer.</p></section>';
};

// Gemeinsame Zellen der DB-Tabellen: Wareneinsatz mit Quellen-Kürzel, DB farbig.
PCBBoard.prototype.dbCells = function (p) {
	var self = this;
	var srcTag = p.cost_source === 'bom'
		? ' <span class="muted" style="font-size:.75rem" title="Wareneinsatz aus Stücklistenwert (BOM)">SL</span>'
		: (p.cost_source === 'ek'
			? ' <span class="muted" style="font-size:.75rem" title="Wareneinsatz aus letztem Einkaufspreis">EK</span>'
			: '');
	var cost = p.cost == null ? '<span class="muted">—</span>' : self.eur(p.cost) + srcTag;
	var margin, marginPct;
	if (p.margin == null) {
		margin = '<span class="muted">—</span>';
		marginPct = '<span class="muted">kein EK/keine Stückliste</span>';
	} else {
		var col = p.margin >= 0 ? 'var(--good)' : 'var(--critical)';
		margin = '<span style="color:' + col + ';font-weight:650">' + self.eur(p.margin) + '</span>';
		marginPct = '<span style="color:' + col + '">' + self.pct(p.margin_pct) + '</span>';
	}
	return { cost: cost, margin: margin, marginPct: marginPct };
};

PCBBoard.prototype.productFlopsHtml = function (m) {
	var self = this;
	var items = m.product_flops || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (p, idx) {
		var c = self.dbCells(p);
		return '<tr' + (p.margin < 0 ? ' class="late"' : '') + '><td>' + (idx + 1) + '</td>' +
			'<td title="' + self.esc(p.item_name || '') + '">' +
			self.esc(p.item_code || p.item_name) + '</td>' +
			'<td class="num">' + self.eur(p.revenue) + '</td>' +
			'<td class="num">' + self.pct(p.share_pct) + '</td>' +
			'<td class="num">' + c.cost + '</td>' +
			'<td class="num">' + c.margin + '</td>' +
			'<td class="num">' + c.marginPct + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Flop 5 Produkte im ' + self.esc(this.monthLabel(m)) +
		' nach Deckungsbeitrag <i class="muted" style="font-size:.78rem;font-weight:400">' +
		'— schwächster Beitrag zuerst</i></figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Produkt</th><th class="num">Umsatz</th>' +
		'<th class="num">Anteil</th>' +
		'<th class="num">Wareneinsatz</th><th class="num">DB</th><th class="num">DB %</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Sortiert nach absolutem ' +
		'Deckungsbeitrag: ein vierstelliger Verlust wiegt schwerer als ein Cent-Verlust am ' +
		'Kleinteil. Produkte ohne EK und ohne Stückliste sind nicht bewertbar und bleiben außen vor.</p></section>';
};

PCBBoard.prototype.productMarginsYearHtml = function (m) {
	var self = this;
	var d = m.product_margins_year || {};
	var items = d.rows || [];
	if (!items.length) {
		return '';
	}
	function deltaTag(v) {
		if (v == null) {
			return ' <span class="muted" style="font-size:.78rem">neu</span>';
		}
		var up = v >= 0;
		return ' <span style="color:' + (up ? 'var(--good)' : 'var(--critical)') +
			';font-weight:650;font-size:.8rem">' + (up ? '▲ +' : '▼ −') + self.eur(Math.abs(v)) + '</span>';
	}
	var rows = items.map(function (p, idx) {
		var c = self.dbCells(p);
		return '<tr><td>' + (idx + 1) + '</td>' +
			'<td title="' + self.esc(p.item_name || '') + '">' +
			self.esc(p.item_code || p.item_name) + '</td>' +
			'<td class="num">' + self.eur(p.revenue) + '</td>' +
			'<td class="num">' + self.pct(p.share_pct) + '</td>' +
			'<td class="num">' + c.cost + '</td>' +
			'<td class="num">' + c.margin + '</td>' +
			'<td class="num">' + c.marginPct + '</td>' +
			'<td class="num">' + (p.prev_revenue == null
				? '<span class="muted">—</span>' : self.eur(p.prev_revenue) +
					(p.prev_share_pct != null
						? ' <span class="muted" style="font-size:.76rem">(' +
							self.pct(p.prev_share_pct) + ')</span>' : '')) + '</td>' +
			'<td class="num">' + (p.prev_margin == null
				? '<span class="muted">—</span>'
				: '<span style="color:' + (p.prev_margin >= 0 ? 'var(--good)' : 'var(--critical)') +
					'">' + self.eur(p.prev_margin) + '</span>') + '</td>' +
			'<td class="num">' + deltaTag(p.delta_margin) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Produkte ' + self.esc(String(d.year || '')) +
		' nach Deckungsbeitrag — Jahresvergleich mit ' + self.esc(String(d.prev_year || '')) +
		'</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Produkt</th>' +
		'<th class="num">Umsatz ' + self.esc(String(d.year || '')) + '</th>' +
		'<th class="num">Anteil</th>' +
		'<th class="num">Wareneinsatz</th><th class="num">DB</th><th class="num">DB %</th>' +
		'<th class="num">Umsatz ' + self.esc(String(d.prev_year || '')) + '</th>' +
		'<th class="num">DB ' + self.esc(String(d.prev_year || '')) + '</th>' +
		'<th class="num">DB-Veränderung</th></tr></thead><tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Umsatz ' +
		self.esc(String(d.year || '')) + ' = Jahresanfang bis heute, Vorjahr = komplettes Jahr. ' +
		'Achtung bei der Auslegung: der Wareneinsatz beider Jahre ist mit den HEUTIGEN Stückkosten ' +
		'gerechnet (letzter EK bzw. Stücklistenwert) — ERPNext führt den damaligen Einstandspreis ' +
		'nicht am Rechnungsbeleg. Der Vergleich zeigt also die Entwicklung von Menge und ' +
		'Verkaufspreis bei heutigen Kosten, nicht die damalige Einkaufslage.</p></section>';
};

PCBBoard.prototype.topPurchasesHtml = function (m) {
	var self = this;
	var items = m.top_purchases || [];
	if (!items.length) {
		return '<section class="card"><figcaption>Top 5 Einkäufe (Monat)</figcaption>' +
			'<p class="muted">Noch keine Wareneingangspositionen in diesem Monat.</p></section>';
	}
	var rows = items.map(function (p, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td title="' + self.esc(p.item_name || '') + '">' +
			self.esc(p.item_code || p.item_name) + '</td>' +
			'<td class="num">' + self.eur(p.net_total) + '</td>' +
			'<td class="num">' + self.pct(p.share_pct) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Einkäufe (Monat, Netto-Warenwert)</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Artikel</th><th class="num">Warenwert</th>' +
		'<th class="num">Anteil</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Anteil = am gesamten ' +
		'Wareneingangswert des Monats.</p></section>';
};

PCBBoard.prototype.profitHistoryHtml = function (m) {
	var self = this;
	var ph = m.profit_history || {};
	var months = ph.months || [];
	if (!months.length) {
		return '';
	}
	var names = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
	var medals = { 1: '🥇', 2: '🥈', 3: '🥉' };
	var rows = months.map(function (r) {
		var mi = parseInt(r.month.slice(5), 10) - 1;
		var lbl = (names[mi] || r.month) + ' ' + r.month.slice(0, 4);
		if (r.is_current) lbl += ' (läuft)';
		function colored(v) {
			return '<td class="num" style="color:' + (v >= 0 ? 'var(--good)' : 'var(--critical)') +
				';font-weight:650">' + self.eur(v) + '</td>';
		}
		var rank = '<td class="num muted">—</td>';
		if (r.rank) {
			rank = '<td class="num"' + (r.rank <= 3 ? ' style="font-weight:650"' : '') + '>' +
				(medals[r.rank] || '') + ' ' + r.rank + '.' +
				(r.ratio != null ? ' <span class="muted" style="font-size:.78rem">(' +
					String(r.ratio.toFixed(2)).replace('.', ',') + '×)</span>' : '') + '</td>';
		}
		// Jahreswechsel optisch markieren.
		var boundary = (mi === 0) ? ' style="border-top:2px solid var(--border)"' : '';
		var opacity = r.is_current ? ' style="opacity:.75"' : '';
		var trAttr = boundary || opacity;
		return '<tr' + trAttr + '><td>' + self.esc(lbl) + '</td>' +
			'<td class="num">' + self.eur(r.revenue) + '</td>' +
			'<td class="num">' + self.eur(r.goods_receipts) + '</td>' +
			'<td class="num">' + self.eur(r.fixed_costs) + '</td>' +
			colored(r.profit) + colored(r.cumulative) + rank + '</tr>';
	}).join('');

	// Trend-Indikator für die kumulierte Kurve (letzter abgeschlossener Monat).
	var trendBadge = '';
	if (ph.trend_value != null) {
		var up = ph.trend_value >= 0;
		trendBadge = ' <span style="color:' + (up ? 'var(--good)' : 'var(--critical)') +
			';font-weight:650">' + (up ? '▲ steigend' : '▼ fallend') + ' (' +
			(up ? '+' : '−') + self.eur(Math.abs(ph.trend_value)) + ' im ' +
			self.esc(String(ph.trend_last_month || '')) + ')</span>';
	}
	var sinceTotal = ph.since_prev_total != null ? ph.since_prev_total : 0;
	return '<section class="card"><figcaption>Gewinn/Verlust je Monat — kumuliert seit ' +
		self.esc(String(ph.prev_year != null ? ph.prev_year : '')) +
		' (Rang = bestes Umsatz-zu-Kosten-Verhältnis)</figcaption>' +
		'<p class="m" style="margin:0 0 8px">Kumuliert bis heute: <b style="color:' +
		(sinceTotal >= 0 ? 'var(--good)' : 'var(--critical)') + '">' + self.eur(sinceTotal) + '</b>' +
		trendBadge + '</p>' +
		'<table class="tbl"><thead><tr><th>Monat</th><th class="num">Umsatz</th>' +
		'<th class="num">Wareneingänge</th><th class="num">Fixkosten</th>' +
		'<th class="num">Gewinn/Verlust</th><th class="num">kumuliert seit ' +
		self.esc(String(ph.prev_year != null ? ph.prev_year : '')) + '</th><th class="num">Rang</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Annahme: Personalkosten und Miete ' +
		'gleichbleibend (' + self.eur(ph.fixed_costs_monthly || 0) + '/Monat, PCB Board Settings); ' +
		'variable Kosten = im jeweiligen Monat gebuchte Wareneingänge.</p></section>';
};

PCBBoard.prototype.recentReceiptsHtml = function (m) {
	var self = this;
	var items = m.recent_receipts || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (r) {
		return '<tr><td><a href="/app/purchase-receipt/' + encodeURIComponent(r.name) +
			'" target="_blank">' + self.esc(r.name) + '</a></td>' +
			'<td>' + self.esc(r.supplier) + '</td>' +
			'<td class="num">' + (r.positions != null ? r.positions : '—') + '</td>' +
			'<td class="num">' + self.eur(r.net_total) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Letzte 5 Wareneingänge</figcaption>' +
		'<table class="tbl"><thead><tr><th>WE-Nr.</th><th>Lieferant</th>' +
		'<th class="num">Positionen</th><th class="num">Gesamt (netto)</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.mailTabHtml = function (m) {
	var self = this;
	var mail = m.mail || {};
	var items = mail.items || [];
	var boxes = mail.mailboxes || [];
	var win = mail.window_hours;
	var winlbl = win ? 'letzte ' + win + ' h' : 'aktuell';

	var connectBar = '';
	if (!m.outlook_connected) {
		connectBar =
			'<div class="connectbar">📪 Kein Postfach verbunden — klicke „Postfach verbinden", ' +
			'damit deine Mails hier erscheinen.<button class="btn primary small" id="pcb-connect">Postfach verbinden</button></div>';
	} else {
		connectBar =
			'<div class="connectbar ok">✅ Postfach verbunden.' +
			'<button class="btn ghost small" id="pcb-disconnect">Trennen</button></div>';
	}

	// Feste Farbe je Postfach — auf einen Blick erkennbar, woher eine Mail kommt.
	var mbPalette = ['#2a78d6', '#1baf7a', '#eda100', '#c30f3b', '#7b52d6', '#0c8a8c', '#d0631b'];
	this._mbColors = {};
	var self2 = this;
	boxes.forEach(function (b, idx) {
		self2._mbColors[b.name] = mbPalette[idx % mbPalette.length];
	});
	function mbColor(name) { return self2._mbColors[name] || 'var(--brand-teal)'; }

	// Auswahl aus dem Instanzzustand zeichnen, nicht fest auf „Alle": nach einem
	// Hintergrund-Refresh filterte das Board sonst weiter nach einem Postfach,
	// während oben „Alle" markiert war.
	var chips = '<button class="chip' + (self.selMb === 'all' ? ' active' : '') +
		'" data-mb="all">Alle</button>';
	boxes.forEach(function (b) {
		var col = mbColor(b.name);
		chips += '<button class="chip' + (self.selMb === b.name ? ' active' : '') +
			'" data-mb="' + self.esc(b.name) + '" ' +
			'style="border-left:4px solid ' + col + '">' +
			self.esc(self.shortBox(b.name)) + ' <span class="chip-n">' + b.total + '</span></button>';
	});

	var tiles =
		'<div class="mini" id="pcb-mail-counts">' +
		'<div class="b"><div class="v" data-count="total">' + (mail.total || 0) + '</div><div class="k">Neu (' + winlbl + ')</div></div>' +
		'<div class="b"><div class="v" data-count="relevant" style="color:var(--series-1)">' + (mail.relevant || 0) + '</div><div class="k">Zu beantworten</div></div>' +
		'<div class="b"><div class="v" data-count="info">' + (mail.info || 0) + '</div><div class="k">Nur Info</div></div>' +
		'<div class="b"><div class="v" data-count="high" style="color:var(--critical)">' + (mail.high_priority || 0) + '</div><div class="k">Dringend</div></div>' +
		'</div>';

	function catBtn(key, label) {
		return '<button class="' + (self.selCat === key ? 'active' : '') + '" data-cat="' + key +
			'">' + label + '</button>';
	}
	var controls =
		'<div class="mailctl"><div class="segbtns" id="pcb-cat-filter">' +
		catBtn('all', 'Alle') + catBtn('relevant', 'Zu beantworten') +
		catBtn('high', 'Dringend') + catBtn('info', 'Info') +
		'</div><input type="search" id="pcb-mail-search" placeholder="Suche: Absender, Betreff …" ' +
		'value="' + self.esc(self.qRaw || '') + '"></div>';

	this._mailByMid = {};
	var cards = items.map(function (i) {
		var rel = i.category === 'relevant';
		var prio = i.priority === 'high' ? 'high' : 'normal';
		var sender = i.sender_name || i.sender || '';
		var subj = i.subject || '';
		var subjHtml;
		if (i.graph_id) {
			var eid = encodeURIComponent(i.graph_id);
			var outlookUrl = 'https://outlook.office.com/mail/deeplink/read/' + eid + '?ItemID=' + eid + '&exvsurl=1';
			subjHtml = '<a href="' + outlookUrl + '" target="_blank" class="mc-subj" title="In Outlook öffnen">' + self.esc(subj) + '</a>';
		} else {
			subjHtml = '<span class="mc-subj">' + self.esc(subj) + '</span>';
		}
		var reason = i.reason || '';
		var draft = (i.draft || '').trim();
		var preview = (i.body_preview || '').trim();
		var searchTxt = (sender + ' ' + subj + ' ' + reason).toLowerCase();
		var dot = prio === 'high' ? '<span class="mc-dot hi" title="dringend"></span>' : '<span class="mc-dot"></span>';
		var pill = rel ? '<span class="pill rel">Antwort</span>' : '<span class="pill info">Info</span>';
		var can = !!(draft || preview);
		var chev = can ? '<span class="mc-chev">▾</span>' : '';
		var mid = i.internet_message_id || '';
		if (mid) {
			self._mailByMid[mid] = i;
		}
		var replied = i.is_replied === true;
		var timeStr = '';
		if (i.received_at) {
			var d = new Date(i.received_at);
			timeStr = d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
		}
		// Kein "ungelesen"-Badge mehr: der Graph-Abruf holt nur noch ungelesene
		// Mails, der Badge wäre auf jeder Karte identisch.
		var actions = '<span class="mc-actions">' +
			(timeStr ? '<span class="mc-time">' + timeStr + '</span>' : '') +
			(replied ? '<span class="mc-badge replied">✓ beantwortet</span>' : '') +
			(i.assigned_to_name
				? '<span class="mc-badge assignee" title="Klicken zum Entfernen">👤 ' +
					self.esc(i.assigned_to_name) + ' ✕</span>'
				: '') +
			(mid ? '<button class="mc-assign-btn" type="button">+ Zuweisen</button>' : '') +
			'</span>';
		var col = mbColor(i.mailbox);
		var head = '<div class="mc-head' + (can ? '' : ' nodraft') + '">' + dot + pill +
			'<span class="mc-box" style="color:' + col + ';background:color-mix(in srgb,' + col + ' 14%,transparent)">' +
			self.esc(self.shortBox(i.mailbox)) + '</span>' +
			'<span class="mc-sender">' + self.esc(sender) + '</span>' +
			subjHtml +
			'<span class="mc-reason">' + self.esc(reason) + '</span>' + actions + chev + '</div>';
		var isOpen = can && self._openMids && self._openMids[mid];
		var draftBlock = '';
		if (can) {
			var inner = '';
			if (preview) {
				inner += '<div class="mc-draft-lbl">Vorschau:</div>' +
					'<pre class="preview-text">' + self.esc(preview) + '</pre>';
			}
			if (draft) {
				inner += '<div class="mc-draft-lbl">Antwortvorschlag ' +
					'(zum Kopieren – wird nicht automatisch gesendet):</div>' +
					'<pre class="draft-text">' + self.esc(draft) + '</pre>' +
					'<button class="copybtn" type="button">📋 Kopieren</button>';
			}
			draftBlock = '<div class="mc-draft"' + (isOpen ? '' : ' hidden') + '>' + inner + '</div>';
		}
		return '<div class="mailcard' + (can ? ' has-draft' : '') + (isOpen ? ' open' : '') +
			'" style="border-left:4px solid ' + col + '" data-mb="' + self.esc(i.mailbox) + '" ' +
			'data-cat="' + (rel ? 'relevant' : 'info') + '" data-prio="' + prio + '" data-mid="' + self.esc(mid) + '" ' +
			'data-text="' + self.esc(searchTxt) + '">' + head + draftBlock + '</div>';
	});
	var cardsHtml = cards.length
		? '<div id="pcb-mail-list">' + cards.join('') + '</div>'
		: '<p class="muted">Keine Mails im Zeitfenster.</p>';
	var empty = '<p class="muted" id="pcb-mail-empty" hidden>Keine Treffer für die aktuelle Auswahl.</p>';

	return '<section class="card"><div class="sec-h"><h2>Posteingang</h2>' +
		'<span class="muted">alle Postfächer im Überblick</span></div>' +
		connectBar + '<div class="chips" id="pcb-mb-chips">' + chips + '</div>' + tiles + controls + cardsHtml + empty +
		'</section>';
};

PCBBoard.prototype.bindMailInteractions = function () {
	var self = this;
	var root = this.$root;

	root.find('#pcb-connect').on('click', function () {
		self.connectOutlook();
	});
	root.find('#pcb-disconnect').on('click', function () {
		self.disconnectOutlook();
	});

	function applyFilter() {
		var cards = root.find('.mailcard');
		var shown = 0;
		var c = { total: 0, relevant: 0, info: 0, high: 0 };
		cards.each(function () {
			var $c = $(this);
			var mbOk = self.selMb === 'all' || $c.data('mb') === self.selMb;
			if (mbOk) {
				c.total++;
				if ($c.data('cat') === 'relevant') c.relevant++;
				else c.info++;
				if ($c.data('prio') === 'high') c.high++;
			}
			var catOk = self.selCat === 'all' ||
				(self.selCat === 'info' && $c.data('cat') === 'info') ||
				(self.selCat === 'relevant' && $c.data('cat') === 'relevant') ||
				(self.selCat === 'high' && $c.data('prio') === 'high');
			var qOk = !self.q || String($c.data('text')).indexOf(self.q) >= 0;
			var vis = mbOk && catOk && qOk;
			$c.toggle(vis);
			if (vis) shown++;
		});
		root.find('#pcb-mail-empty').prop('hidden', shown > 0);
		root.find('#pcb-mail-counts [data-count]').each(function () {
			$(this).text(c[$(this).data('count')]);
		});
	}

	root.find('#pcb-mb-chips .chip').on('click', function () {
		root.find('#pcb-mb-chips .chip').removeClass('active');
		$(this).addClass('active');
		self.selMb = $(this).data('mb');
		applyFilter();
	});
	root.find('#pcb-cat-filter button').on('click', function () {
		root.find('#pcb-cat-filter button').removeClass('active');
		$(this).addClass('active');
		self.selCat = $(this).data('cat');
		applyFilter();
	});
	root.find('#pcb-mail-search').on('input', function () {
		// qRaw = was der Nutzer sieht, q = normalisierter Suchschlüssel. Getrennt,
		// damit ein Neuaufbau die Eingabe nicht kleingeschrieben zurückschreibt.
		self.qRaw = $(this).val();
		self.q = self.qRaw.toLowerCase().trim();
		applyFilter();
	});
	root.find('.mailcard.has-draft .mc-head').on('click', function () {
		var $card = $(this).parent();
		var $d = $card.find('.mc-draft');
		var open = !$card.hasClass('open');
		$card.toggleClass('open', open);
		$d.prop('hidden', !open);
		// Offen-Zustand merken, damit ein Hintergrund-Refresh (Neurendern) die
		// Vorschau nicht zuklappt — bleibt offen, bis aktiv geschlossen wird.
		var mid = $card.data('mid');
		if (mid) {
			if (open) self._openMids[mid] = true;
			else delete self._openMids[mid];
		}
	});
	root.find('.copybtn').on('click', function (e) {
		e.stopPropagation();
		var txt = $(this).parent().find('.draft-text').text();
		if (navigator.clipboard && navigator.clipboard.writeText) {
			navigator.clipboard.writeText(txt).then(
				function () {
					self.toast('Antwort kopiert ✓');
				},
				function () {
					self.toast('Kopieren nicht möglich');
				}
			);
		}
	});
	root.find('.mc-assign-btn').on('click', function (e) {
		e.stopPropagation();
		var mid = $(this).closest('.mailcard').data('mid');
		var item = self._mailByMid[mid];
		if (item) {
			self.openAssignDialog(item);
		}
	});
	root.find('.mc-badge.assignee').on('click', function (e) {
		e.stopPropagation();
		var mid = $(this).closest('.mailcard').data('mid');
		if (!mid) return;
		frappe.call({
			method: 'pcb_board.api.unassign_mail',
			type: 'POST',
			args: { internet_message_id: mid },
		}).then(function () {
			self.toast('Zuweisung entfernt');
			self.load();
		});
	});
	applyFilter();
};

// Beschriftung einer Balken-Markierung: mittig über/unter dem Strich. Nur an den
// äußersten Rändern wird links/rechts ausgerichtet, damit nichts aus der Karte
// läuft — die Balken-Skala hat dafür etwas Luft (siehe scaleMax).
PCBBoard.prototype.markerLbl = function (pct, html) {
	var style;
	if (pct <= 3) {
		style = 'left:0';
	} else if (pct >= 97) {
		style = 'right:0';
	} else {
		style = 'left:' + pct.toFixed(2) + '%;transform:translateX(-50%)';
	}
	return '<span class="mlbl" style="' + style + '">' + html + '</span>';
};

// Mehrere Beschriftungen über/unter einem Balken: liegen zwei Markierungen zu
// dicht beieinander, wandert die zweite in eine eigene Zeile statt zu überlappen.
PCBBoard.prototype.lblRowsHtml = function (rowCls, items) {
	var self = this;
	var rows = [];
	items.slice().sort(function (a, b) { return a.pct - b.pct; }).forEach(function (it) {
		for (var i = 0; i < rows.length; i++) {
			var free = rows[i].every(function (o) { return Math.abs(o.pct - it.pct) >= 16; });
			if (free) { rows[i].push(it); return; }
		}
		rows.push([it]);
	});
	return rows.map(function (r) {
		return '<div class="mlbl-row ' + rowCls + '">' +
			r.map(function (o) { return self.markerLbl(o.pct, o.html); }).join('') + '</div>';
	}).join('');
};

PCBBoard.prototype.revenueTabHtml = function (m) {
	var self = this;
	var fc = m.forecast;
	var statusMap = {
		green: ['var(--good)', 'Auf Kurs', '▲'],
		amber: ['var(--warning)', 'Knapp', '▶'],
		red: ['var(--critical)', 'Unter Ziel', '▼'],
	};
	var st = statusMap[fc.status] || statusMap.amber;
	var costsTotal = (m.costs && m.costs.total) || 0;
	var ph = m.profit_history || {};
	var py = m.prev_year || {};
	var profitMtd = fc.mtd - costsTotal;
	var profitForecast = fc.forecast - costsTotal;
	var ytd = m.ytd_revenue || 0;
	// G/V „Jahresanfang bis heute" = abgeschlossene Monate + laufender Monat (Ist).
	var ytdProfit = ph.ytd_profit != null ? ph.ytd_profit : ((ph.carry_forward || 0) + profitMtd);
	var year = (m.as_of || '').slice(0, 4);
	var pyYear = py.year != null ? String(py.year) : '';
	var monthNames = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
		'August', 'September', 'Oktober', 'November', 'Dezember'];
	var monthName = monthNames[(py.month || 1) - 1] || '';
	var curMonthLbl = monthName ? monthName + ' ' + year : 'laufender Monat';
	var pyMonthLbl = monthName ? monthName + ' ' + pyYear : 'Vorjahresmonat';

	function deltaArrow(delta, base, titleText) {
		var pctv = Math.round((delta / base) * 100);
		var up = delta >= 0;
		return ' <span class="vdelta" style="color:' + (up ? 'var(--good)' : 'var(--critical)') + '"' +
			(titleText ? ' title="' + self.esc(titleText) + '"' : '') + '>' +
			(up ? '▲ +' : '▼ −') + Math.abs(pctv) + ' %</span>';
	}
	function gvCol(v) { return v >= 0 ? 'var(--good)' : 'var(--critical)'; }
	function signed(v) { return (v >= 0 ? '+' : '−') + self.eur(Math.abs(v)); }
	// Werteverdichtung: zusammengehörende Werte in EINEM weißen Feld — Überschrift
	// = Kennzahl, je Zeile ein Zeitraum. Gleiche Zeilenfolge in den Umsatz-Feldern,
	// damit laufendes Jahr und Vorjahr direkt untereinander vergleichbar sind.
	function vcard(title, rows) {
		var body = rows.filter(Boolean).map(function (r) {
			return '<div class="vrow"><span class="vk">' + r[0] + '</span>' +
				'<span class="vv"' + (r[2] ? ' style="color:' + r[2] + '"' : '') + '>' + r[1] + '</span></div>';
		}).join('');
		return '<section class="card vcard"><figcaption>' + title + '</figcaption>' + body + '</section>';
	}

	var tiles =
		'<div class="tiles rev-tiles">' +
		'<div class="tile hero"><p class="k">Ist-Umsatz (Netto)</p><div class="v">' + self.eur(fc.mtd) + '</div>' +
		'<div class="m">' + fc.bd_elapsed + ' von ' + fc.bd_total + ' Werktagen</div></div>' +
		'<div class="tile"><p class="k">Prognose Monatsende</p><div class="v">' + self.eur(fc.forecast) + '</div>' +
		'<div class="m"><span class="badge" style="background:' + st[0] + '">' + st[2] + ' ' + st[1] + ' · ' + self.pct(fc.attainment_pct) + '</span></div></div>' +
		'<div class="tile"><p class="k">Nötig je Restwerktag</p><div class="v">' + self.eur(fc.required_daily) + '</div>' +
		'<div class="m">an ' + fc.bd_remaining + ' Werktagen</div></div>' +
		'</div>';

	// Umsatz laufendes Jahr — Prognose und YTD je mit Vorjahresvergleich. Der
	// Monatsvergleich ist bewusst voller Monat ggü. vollem Vorjahresmonat.
	var revCurCard = vcard('Umsatz ' + self.esc(year), [
		[self.esc(curMonthLbl) + ' (Prognose)',
			self.eur(fc.forecast) + (py.total > 0
				? deltaArrow(fc.forecast - py.total, py.total,
					'Prognose ' + self.eur(fc.forecast) + ' ggü. vollem Vorjahresmonat ' +
					self.eur(py.total) + ' (' + pyMonthLbl + ')')
				: '')],
		['Jahresanfang bis heute',
			self.eur(ytd) + (py.ytd_same_day > 0
				? deltaArrow(ytd - py.ytd_same_day, py.ytd_same_day,
					'Vorjahr bis zum selben Kalendertag: ' + self.eur(py.ytd_same_day))
				: '')],
	]);

	// Umsatz Vorjahr — Monat zuerst, dann die Jahres-Zeiträume; gleiche
	// Zeilenfolge wie im laufenden Jahr, damit sich beide Felder vergleichen lassen.
	var revPrevCard = '';
	if (py.full_year_total || py.total) {
		revPrevCard = vcard('Umsatz ' + self.esc(pyYear), [
			[self.esc(pyMonthLbl), self.eur(py.total)],
			['Jahresanfang bis heute <i class="vhint" title="Vorjahr bis zum selben Kalendertag — fairer Vergleich">' +
				'(bis zum selben Tag)</i>', self.eur(py.ytd_same_day)],
			['komplettes Jahr', self.eur(py.full_year_total)],
		]);
	}

	var gvRows = [
		[self.esc(curMonthLbl) + ' (Prognose)', signed(profitForecast), gvCol(profitForecast)],
		['Jahresanfang bis heute', signed(ytdProfit), gvCol(ytdProfit)],
	];
	if (py.full_year_total || py.total) {
		var pyp = py.full_year_profit || 0;
		gvRows.push(['komplettes Vorjahr (' + self.esc(pyYear) + ')', signed(pyp), gvCol(pyp)]);
	}
	// „Gesamt seit <Vorjahr>": Vorjahres-G/V mit dem laufenden Vortrag fortgeführt,
	// Trend = Richtung des letzten abgeschlossenen Monats.
	if (ph.prev_year != null && ph.since_prev_completed != null) {
		var sp = ph.since_prev_completed;
		var trendHtml = '';
		if (ph.trend_value != null) {
			var upT = ph.trend_value >= 0;
			trendHtml = ' <span class="vdelta" style="color:' + (upT ? 'var(--good)' : 'var(--critical)') +
				'" title="letzter abgeschlossener Monat ' + self.esc(String(ph.trend_last_month || '')) + '">' +
				(upT ? '▲ +' : '▼ −') + self.eur(Math.abs(ph.trend_value)) + '</span>';
		}
		gvRows.push(['Gesamt seit ' + self.esc(String(ph.prev_year)) +
			' <i class="vhint">(kumuliert)</i>', signed(sp) + trendHtml, gvCol(sp)]);
	}
	var vcards = '<div class="vcards">' + revCurCard + revPrevCard +
		vcard('Gewinn/Verlust', gvRows) + '</div>';

	// Balken-Skala mit 6 % Luft: so klebt die Ziel-Markierung nicht am rechten
	// Rand und ihre Beschriftung hat mittig über dem Strich Platz.
	var scaleMax = (Math.max(m.target, fc.forecast_high, costsTotal) || 1) * 1.06;
	var mtdW = (fc.mtd / scaleMax) * 100;
	var projW = (Math.max(fc.forecast - fc.mtd, 0) / scaleMax) * 100;
	var targetPos = (m.target / scaleMax) * 100;
	var costsPos = (costsTotal / scaleMax) * 100;

	var verdictText = profitMtd >= 0
		? '✅ Kosten bereits gedeckt — aktuell ' + self.eur(profitMtd) + ' im Plus.'
		: '🔻 Noch ' + self.eur(Math.abs(profitMtd)) + ' bis zur Kostendeckung (Ist).';

	// Beschriftung direkt an den Balken-/Marker-Positionen: Ziel (schwarz) und
	// Kosten (rot) mittig über ihrem Strich, Ist/Prognose unter dem Balkenende.
	var meter =
		'<figcaption>Zielerreichung</figcaption><div class="meter-wrap">' +
		this.lblRowsHtml('top', [
			{ pct: targetPos, html: '<span class="target-lbl">Ziel ' + self.eur(m.target) + '</span>' },
			{ pct: costsPos, html: '<span class="costs-lbl">Kosten ' + self.eur(costsTotal) + '</span>' },
		]) +
		'<div class="meter"><div class="meter-row">' +
		'<div class="fill" style="width:' + mtdW.toFixed(2) + '%;background:var(--series-1)"></div>' +
		'<div class="proj" style="width:' + projW.toFixed(2) + '%;background:' + st[0] + '"></div>' +
		'</div><div class="mk" style="left:' + targetPos.toFixed(2) + '%" title="Umsatzziel"></div>' +
		'<div class="mk costs" style="left:' + costsPos.toFixed(2) + '%" title="Gesamtkosten (Kostendeckung)"></div></div>' +
		this.lblRowsHtml('bot', [
			{ pct: mtdW, html: '<span style="color:var(--series-1)">Ist ' + self.eur(fc.mtd) + '</span>' },
			{ pct: mtdW + projW, html: '<span style="color:' + st[0] + '">Prognose ' + self.eur(fc.forecast) + '</span>' },
		]) +
		'<p class="meter-verdict" style="color:' + gvCol(profitMtd) + '">' + verdictText + '</p></div>';

	// Zieldeckung direkt unter der Zielerreichung — gleiche Karte, gleiche
	// Beschriftungs-Logik (Ziel schwarz, mittig über dem Strich).
	var bars = '<section class="card">' + meter +
		'<figcaption class="bar2">Zieldeckung inkl. Pipeline</figcaption>' +
		this.coverageBarHtml(m) + '</section>';

	return tiles + vcards + bars + this.topProductsHtml(m) + this.topCustomersHtml(m) +
		this.topCustomersYearHtml(m) +
		this.tipsHtml(m);
};

PCBBoard.prototype.topCustomersHtml = function (m) {
	var self = this;
	var items = m.top_customers || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (c, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td>' + self.esc(c.customer) + '</td>' +
			'<td class="num">' + self.eur(c.net_total) + '</td>' +
			'<td class="num">' + self.pct(c.share_pct) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Kunden im ' + self.esc(this.monthLabel(m)) +
		' nach Netto-Umsatz <i class="muted" style="font-size:.78rem;font-weight:400">— Klumpenrisiko im Blick behalten</i></figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Kunde</th><th class="num">Umsatz</th>' +
		'<th class="num">Anteil</th></tr></thead><tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.topCustomersYearHtml = function (m) {
	var self = this;
	var d = m.top_customers_year || {};
	var items = d.rows || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (c, idx) {
		var medal = idx === 0 ? '🥇 ' : (idx === 1 ? '🥈 ' : (idx === 2 ? '🥉 ' : ''));
		var prev = c.prev_net_total == null
			? '<span class="muted" title="Kein Umsatz im Vorjahr — neuer oder reaktivierter Kunde">neu</span>'
			: self.eur(c.prev_net_total);
		var delta = '<span class="muted">—</span>';
		if (c.delta_pct != null) {
			var up = c.delta_pct >= 0;
			delta = '<span style="color:' + (up ? 'var(--good)' : 'var(--critical)') +
				';font-weight:650">' + (up ? '▲ +' : '▼ −') +
				Math.abs(Math.round(c.delta_pct * 100)) + ' %</span>';
		}
		return '<tr><td>' + medal + (idx + 1) + '</td>' +
			'<td class="col-customer" title="' + self.esc(c.customer) + '">' +
			self.esc(c.customer) + '</td>' +
			'<td class="num">' + self.eur(c.net_total) + '</td>' +
			'<td class="num">' + self.pct(c.share_pct) + '</td>' +
			'<td class="num">' + c.invoices + '</td>' +
			'<td class="num">' + prev + '</td>' +
			'<td class="num">' + delta + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 10 Kunden ' + self.esc(String(d.year || '')) +
		' nach Netto-Umsatz <i class="muted" style="font-size:.78rem;font-weight:400">— ' +
		'Jahresanfang bis heute</i></figcaption>' +
		'<p class="m" style="margin:0 0 8px">Diese ' + items.length + ' Kunden stehen für <b>' +
		self.pct(d.top_share_pct) + '</b> des Jahresumsatzes (' + self.eur(d.year_total) +
		' von ' + (d.customer_count || 0) + ' Kunden insgesamt).</p>' +
		'<table class="tbl"><thead><tr><th>#</th><th class="col-customer">Kunde</th>' +
		'<th class="num">Umsatz ' + self.esc(String(d.year || '')) + '</th>' +
		'<th class="num">Anteil</th><th class="num">Rechnungen</th>' +
		'<th class="num">' + self.esc(String(d.prev_year || '')) + ' gesamt</th>' +
		'<th class="num">Entwicklung</th></tr></thead><tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Die Spalte „' +
		self.esc(String(d.prev_year || '')) + ' gesamt" ist das KOMPLETTE Vorjahr. Die ' +
		'Entwicklung vergleicht also einen laufenden Zeitraum mit einem abgeschlossenen ' +
		'Jahr und fällt früh im Jahr zwangsläufig negativ aus — sie zeigt den Stand ' +
		'gegenüber dem Vorjahresergebnis, nicht den Trend.</p></section>';
};

PCBBoard.prototype.topSuppliersYearHtml = function (m) {
	var self = this;
	var d = m.top_suppliers_year || {};
	var items = d.rows || [];
	if (!items.length) {
		return '';
	}
	var rows = items.map(function (s, idx) {
		var medal = idx === 0 ? '🥇 ' : (idx === 1 ? '🥈 ' : (idx === 2 ? '🥉 ' : ''));
		var prev = s.prev_net_total == null
			? '<span class="muted" title="Kein Wareneingang im Vorjahr — neuer Lieferant">neu</span>'
			: self.eur(s.prev_net_total);
		var delta = '<span class="muted">—</span>';
		if (s.delta_pct != null) {
			// Beim Einkauf ist „mehr" nicht automatisch gut, deshalb neutral
			// gefärbt: die Richtung wird gezeigt, nicht bewertet.
			var up = s.delta_pct >= 0;
			delta = '<span style="font-weight:650">' + (up ? '▲ +' : '▼ −') +
				Math.abs(Math.round(s.delta_pct * 100)) + ' %</span>';
		}
		return '<tr><td>' + medal + (idx + 1) + '</td>' +
			'<td class="col-customer" title="' + self.esc(s.supplier) + '">' +
			self.esc(s.supplier) + '</td>' +
			'<td class="num">' + self.eur(s.net_total) + '</td>' +
			'<td class="num">' + self.pct(s.share_pct) + '</td>' +
			'<td class="num">' + s.receipts + '</td>' +
			'<td class="num">' + prev + '</td>' +
			'<td class="num">' + delta + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 10 Lieferanten ' + self.esc(String(d.year || '')) +
		' nach Netto-Einkauf <i class="muted" style="font-size:.78rem;font-weight:400">— ' +
		'Jahresanfang bis heute</i></figcaption>' +
		'<p class="m" style="margin:0 0 8px">Diese ' + items.length + ' Lieferanten stehen für <b>' +
		self.pct(d.top_share_pct) + '</b> des Jahres-Einkaufs (' + self.eur(d.year_total) +
		' von ' + (d.supplier_count || 0) + ' Lieferanten insgesamt).</p>' +
		'<table class="tbl"><thead><tr><th>#</th><th class="col-customer">Lieferant</th>' +
		'<th class="num">Einkauf ' + self.esc(String(d.year || '')) + '</th>' +
		'<th class="num">Anteil</th><th class="num">Wareneingänge</th>' +
		'<th class="num">' + self.esc(String(d.prev_year || '')) + ' gesamt</th>' +
		'<th class="num">Entwicklung</th></tr></thead><tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Grundlage sind gebuchte ' +
		'Wareneingänge (Netto), nicht Bestellungen. Die Spalte „' +
		self.esc(String(d.prev_year || '')) + ' gesamt" ist das KOMPLETTE Vorjahr — die ' +
		'Entwicklung stellt einen laufenden Zeitraum einem abgeschlossenen Jahr gegenüber ' +
		'und fällt früh im Jahr zwangsläufig negativ aus.</p></section>';
};

PCBBoard.prototype.monthLabel = function (m) {
	var names = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
		'August', 'September', 'Oktober', 'November', 'Dezember'];
	var iso = m.as_of || '';
	var mi = parseInt(iso.slice(5, 7), 10);
	return (names[mi - 1] || '') + ' ' + iso.slice(0, 4);
};

PCBBoard.prototype.topProductsHtml = function (m) {
	var self = this;
	var items = m.top_products || [];
	if (!items.length) {
		return '<section class="card"><figcaption>Top 5 Produkte im ' + self.esc(this.monthLabel(m)) +
			' nach Netto-Umsatz</figcaption>' +
			'<p class="muted">Noch keine Rechnungspositionen in diesem Monat.</p></section>';
	}
	var rows = items.map(function (p, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td title="' + self.esc(p.item_name || '') + '">' +
			self.esc(p.item_code || p.item_name) + '</td>' +
			'<td class="num">' + self.eur(p.net_total) + '</td>' +
			'<td class="num">' + self.pct(p.share_pct) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Produkte im ' + self.esc(this.monthLabel(m)) +
		' nach Netto-Umsatz</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Produkt</th><th class="num">Umsatz</th>' +
		'<th class="num">Anteil</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Anteil = am gesamten ' +
		'Monatsumsatz aller Artikel, nicht nur der gezeigten fünf.</p></section>';
};

PCBBoard.prototype.coverageBarHtml = function (m) {
	var self = this;
	var fc = m.forecast, pl = m.pipeline, target = m.target;
	var scaleMax = (Math.max(target, pl.coverage_after_forecast) || 1) * 1.06;
	var segs = [
		['Ist (Monat)', fc.mtd, 'var(--series-1)'],
		['Prognose-Rest', Math.max(fc.forecast - fc.mtd, 0), 'var(--series-1-soft)'],
		['Abrechnungsbereit', pl.ready_net, 'var(--series-2)'],
		['Unterwegs', pl.in_transit_net, 'var(--series-3)'],
	];
	var rects = segs
		.filter(function (s) { return s[1] > 0; })
		.map(function (s) {
			return '<div class="seg" style="width:' + ((s[1] / scaleMax) * 100).toFixed(2) + '%;background:' + s[2] +
				'" title="' + self.esc(s[0]) + ': ' + self.eur(s[1]) + '"></div>';
		})
		.join('');
	var legend = segs
		.filter(function (s) { return s[1] > 0; })
		.map(function (s) {
			return '<span class="lg"><i style="background:' + s[2] + '"></i>' + self.esc(s[0]) + ' · ' + self.eur(s[1]) + '</span>';
		})
		.join('');
	var coverage = pl.coverage_after_forecast;
	var verdict = coverage >= target ? 'Pipeline deckt das Ziel ✓' : 'Auch mit Pipeline noch ' + self.eur(target - coverage) + ' bis zum Ziel';
	var targetPos = (target / scaleMax) * 100;
	var covPos = (coverage / scaleMax) * 100;
	return '<div class="meter-wrap">' +
		this.lblRowsHtml('top', [
			{ pct: targetPos, html: '<span class="target-lbl">Ziel ' + self.eur(target) + '</span>' },
		]) +
		'<div class="cov-track">' + rects +
		'<div class="cov-target" style="left:' + targetPos.toFixed(2) + '%"></div></div>' +
		this.lblRowsHtml('bot', [
			{ pct: covPos, html: '<span class="cov-sum">Deckung ' + self.eur(coverage) + '</span>' },
		]) +
		'<div class="cov-legend">' + legend + '</div>' +
		'<p class="cov-verdict">' + self.esc(verdict) + '</p></div>';
};

PCBBoard.prototype.tipsHtml = function (m) {
	var self = this;
	var items = m.tips || [];
	if (!items.length) {
		return '<section class="card"><figcaption>🚀 Wo wir pushen können</figcaption>' +
			'<p class="muted">Keine Handlungsempfehlungen – alles im grünen Bereich.</p></section>';
	}
	var rows = items
		.map(function (t) {
			return '<li><span class="tip-eur">' + self.eur(t.impact_eur) + '</span>' +
				'<span class="tip-body"><b>' + self.esc(t.title) + '</b>' +
				'<span class="tip-detail">' + self.esc(t.detail) + '</span></span></li>';
		})
		.join('');
	return '<section class="card"><figcaption>🚀 Wo wir pushen können</figcaption><ol class="tips">' + rows + '</ol></section>';
};

PCBBoard.prototype.outgoingPackagesHtml = function (m) {
	var self = this;
	var b = m.billing;
	var methodLabel = { ups: 'UPS', fallback: 'geschätzt', none: '—' };
	// Ausgehende Pakete (Lieferscheine) in EINER Tabelle, Status als Spalte.
	var staleNames = {};
	(b.stale || []).forEach(function (r) { staleNames[r.name] = true; });
	var staleDays = b.stale_days || 60;
	function tag(r, group) {
		// Regel unverändert (älter als die Klärgrenze), nur die Benennung ist
		// jetzt handlungsorientiert: solche Belege gehören angeschaut, nicht
		// bloß als „alt" abgestempelt.
		if (staleNames[r.name]) {
			return '<span class="dot-hi" title="Lieferschein älter als ' + staleDays +
				' Tage — bitte prüfen">zu klären</span>';
		}
		if (group === 'ready') return '<span class="pill rel">zugestellt – abrechnen</span>';
		if (group === 'transit') return '<span class="pill info">unterwegs</span>';
		return '<span class="muted">Status offen</span>';
	}
	var groups = [['ready', b.ready], ['transit', b.in_transit], ['unknown', b.unknown]];
	var rows = [];
	groups.forEach(function (g) {
		(g[1] || []).forEach(function (r) { rows.push({ r: r, group: g[0] }); });
	});
	// Neuester Versand oben; ohne Datum ans Ende.
	rows.sort(function (a, z) {
		var da = a.r.shipment_date || '', dz = z.r.shipment_date || '';
		if (!da && !dz) return String(a.r.name).localeCompare(String(z.r.name));
		if (!da) return 1;
		if (!dz) return -1;
		return da < dz ? 1 : (da > dz ? -1 : String(a.r.name).localeCompare(String(z.r.name)));
	});
	var totalNet = rows.reduce(function (acc, o) { return acc + (o.r.net_open || 0); }, 0);
	var body = rows.map(function (o) {
		var r = o.r;
		var shipped = r.shipment_date
			? '<span title="' + (r.shipment_date_source === 'ups'
					? 'Versanddatum laut UPS' : 'Datum des Lieferscheins') + '">' +
				self.esc(frappe.datetime.str_to_user(r.shipment_date)) + '</span>' +
				(r.age_days != null
					? ' <span class="muted" style="font-size:.76rem">(' + r.age_days + ' T.)</span>' : '')
			: '<span class="muted">—</span>';
		return '<tr><td class="col-dn"><a href="/app/delivery-note/' + encodeURIComponent(r.name) +
			'" target="_blank">' + self.esc(r.name) + '</a></td>' +
			'<td class="col-dn-customer" title="' + self.esc(r.customer || '') + '">' +
			self.esc(r.customer || '') + '</td>' +
			'<td class="num">' + self.eur(r.net_open) + '</td>' +
			'<td>' + tag(r, o.group) + '</td>' +
			'<td>' + shipped + '</td>' +
			'<td>' + (methodLabel[r.arrival_method] || '—') + '</td></tr>';
	}).join('');
	var table = rows.length
		? '<table class="tbl"><thead><tr><th class="col-dn">Lieferschein</th>' +
			'<th class="col-dn-customer">Kunde</th><th class="num">Netto</th>' +
			'<th>Status</th><th>Versanddatum</th><th>Zustellquelle</th></tr></thead><tbody>' + body +
			'</tbody><tfoot><tr><td colspan="2">Summe (' + rows.length + ')</td>' +
			'<td class="num">' + self.eur(totalNet) + '</td><td colspan="3"></td></tr></tfoot></table>'
		: '<p class="muted">Keine offenen Lieferscheine zur Abrechnung. ✅</p>';

	// Durchlaufzeit-Analyse (Backlog): wie lange warten offene Lieferscheine schon.
	var tp = b.throughput || {};
	var analysis =
		'<div class="tiles" style="margin-bottom:12px">' +
		// Zwei getrennte Beträge: was sofort in Umsatz kann, und was erst geklärt
		// werden muss. Bewusst ohne Überschneidung — ein zugestellter Lieferschein
		// jenseits der Klärgrenze zählt zum Klärfall, nicht zum abrechenbaren Geld.
		'<div class="tile"><p class="k">Jetzt abrechenbar / zu klären</p>' +
		'<div class="split-vals">' +
		'<span class="sv"><span class="sv-v" style="color:var(--good)">' +
		self.eur(b.ready_clear_net) + '</span>' +
		'<span class="sv-k">jetzt abrechenbar · ' + (b.ready_clear_count || 0) +
		' Lieferschein(e)</span></span>' +
		'<span class="sv"><span class="sv-v" style="color:' +
		((b.stale_count || 0) ? 'var(--critical)' : 'var(--text-secondary)') + '">' +
		self.eur(b.stale_net) + '</span>' +
		'<span class="sv-k">zu klären · ' + (b.stale_count || 0) + ' Lieferschein(e) &gt; ' +
		(b.stale_days || 60) + ' T.</span></span>' +
		'</div></div>' +
		'<div class="tile"><p class="k">Ø Wartezeit bis Abrechnung</p>' +
		'<div class="v">' + (tp.open_count ? String(tp.avg_open_age_days).replace('.', ',') + ' Tage' : '—') + '</div>' +
		'<div class="m">' + (tp.open_count ? 'Median ' + String(tp.median_open_age_days).replace('.', ',') +
			' T. · ältester ' + tp.max_open_age_days + ' T.' : 'keine offenen Lieferscheine') + '</div></div>' +
		'<div class="tile"><p class="k">Offene Lieferscheine gesamt</p>' +
		'<div class="v">' + (tp.open_count || 0) + '</div>' +
		'<div class="m">warten auf Abrechnung (Lieferschein erstellt → noch nicht berechnet)</div></div>' +
		'</div>';

	return '<section class="card"><div class="sec-h"><h2>📦 Ausgehende Pakete (Lieferscheine)</h2>' +
		'<span class="muted">zugestellt / unterwegs / zu klären — alles zum Abrechnen</span></div>' +
		analysis + table + '</section>';
};

// ------------------------------------------------------------------------ CSS

var PCB_BOARD_CSS =
	'.pcb-root{--surface-1:#fcfcfb;--plane:#f4f5f3;--text-primary:#0b0b0b;--text-secondary:#52514e;' +
	'--muted:#898781;--grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);' +
	'--series-1:#2a78d6;--series-1-soft:#9ec5f4;--series-2:#1baf7a;--series-3:#eda100;' +
	'--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--brand-teal:#0c8a8c;--brand-red:#c30f3b;' +
	'font-family:var(--font-stack,system-ui,-apple-system,"Segoe UI",sans-serif);color:var(--text-primary);' +
	'background:var(--plane);padding:16px;line-height:1.45}' +
	'.pcb-root.pcb-dark{--surface-1:#1a1a19;--plane:#0d0d0d;--text-primary:#fff;' +
	'--text-secondary:#c3c2b7;--muted:#8a8880;--grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.12);' +
	'--series-1:#3987e5;--series-1-soft:#1c5cab;--series-2:#199e70;--series-3:#c98500;--brand-teal:#14a1a4;--brand-red:#e14b6f}' +
	'.pcb-root *{box-sizing:border-box}.pcb-root h1,.pcb-root h2{margin:0;font-weight:660}' +
	'.pcb-logo .pcb-teal{fill:var(--brand-teal)}.pcb-logo .pcb-red{fill:var(--brand-red)}' +
	'.pcb-logo .pcb-seg{transform-origin:100px 100px}' +
	'.pcb-logo.pulsing{animation:pcbspin 6s linear infinite}' +
	'.pcb-logo.pulsing .pcb-seg{animation:pcbpulse 1.2s ease-in-out infinite;animation-delay:calc(var(--i)*0.12s)}' +
	'.pcb-logo.pulsing .pcb-disc{animation:pcbdisc 1.2s ease-in-out infinite}' +
	'@keyframes pcbpulse{0%,100%{opacity:.28}30%{opacity:1}}' +
	'@keyframes pcbdisc{0%,100%{opacity:.8;transform:scale(.94)}50%{opacity:1;transform:scale(1)}}' +
	'@keyframes pcbspin{to{transform:rotate(360deg)}}' +
	'.hd{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px}' +
	'.hd .brand{display:flex;align-items:center;gap:12px;flex:1;min-width:220px}' +
	'.hd h1{font-size:1.3rem;line-height:1.1;color:var(--text-primary)!important;font-weight:700}' +
	'.hd .tag{color:var(--brand-teal);font-weight:600;font-size:.82rem}' +
	'.hd .slogan{color:var(--brand-red);font-weight:700;font-size:.82rem;margin-top:2px}' +
	'.hd .sub{color:var(--text-secondary);font-size:.82rem;margin-top:2px}' +
	'.hd .actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}' +
	'.pcb-root .btn{border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);' +
	'border-radius:9px;padding:8px 12px;font-size:.85rem;cursor:pointer;font-weight:600}' +
	'.pcb-root .btn.small{padding:5px 10px;font-size:.78rem;margin-left:10px}' +
	'.pcb-root .btn.primary{background:var(--brand-teal);color:#fff;border-color:transparent}' +
	'.pcb-root .btn.ghost{color:var(--text-secondary);font-weight:500}' +
	'.userchip{display:inline-flex;align-items:center;gap:6px;font-size:.82rem;font-weight:600;color:var(--text-secondary);' +
	'background:var(--surface-1);border:1px solid var(--border);border-radius:999px;padding:6px 12px}' +
	'.pcb-root .tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin:4px 0 2px}' +
	'.pcb-root .tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--text-secondary);' +
	'padding:9px 14px;font-size:.92rem;font-weight:600;cursor:pointer;margin-bottom:-1px}' +
	'.pcb-root .tabs button.active{color:var(--brand-teal);border-bottom-color:var(--brand-teal)}' +
	'.pcb-root .tab-panel{display:none}.pcb-root .tab-panel.active{display:block}' +
	'.pcb-root .card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px;margin-top:16px}' +
	'.sec-h{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}' +
	'.sec-h h2{font-size:1.05rem;color:var(--text-primary)!important;font-weight:700}' +
	'.connectbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--plane);border:1px solid var(--border);' +
	'border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:.88rem}' +
	'.connectbar.ok{color:var(--good)}' +
	'.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}' +
	'.chip{border:1px solid var(--border);background:var(--plane);color:var(--text-secondary);' +
	'border-radius:999px;padding:6px 13px;font-size:.84rem;font-weight:600;cursor:pointer}' +
	'.chip.active{background:var(--brand-teal);color:#fff;border-color:transparent}' +
	'.chip-n{opacity:.75;font-weight:700;margin-left:3px}' +
	'.mini{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}' +
	'.mini .b{display:flex;align-items:baseline;gap:6px;background:var(--plane);border:1px solid var(--border);' +
	'border-radius:999px;padding:4px 12px}' +
	'.mini .b .v{font-size:1rem;font-weight:700}.mini .b .k{font-size:.74rem;color:var(--text-secondary)}' +
	'.mailctl{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}' +
	'.segbtns{display:inline-flex;border:1px solid var(--border);border-radius:9px;overflow:hidden}' +
	'.segbtns button{background:var(--surface-1);border:0;border-right:1px solid var(--border);color:var(--text-secondary);' +
	'padding:7px 12px;font-size:.82rem;font-weight:600;cursor:pointer}' +
	'.segbtns button:last-child{border-right:0}.segbtns button.active{background:var(--brand-teal);color:#fff}' +
	'#pcb-mail-search{flex:1;min-width:180px;border:1px solid var(--border);background:var(--plane);color:var(--text-primary);' +
	'border-radius:9px;padding:8px 12px;font-size:.85rem}' +
	'.mailcard{border:1px solid var(--border);border-radius:10px;margin-bottom:8px;background:var(--plane);overflow:hidden;position:relative}' +
	'.mc-head{display:grid;grid-template-columns:auto auto auto 1fr;gap:8px;align-items:center;padding:10px 12px;cursor:default}' +
	'.mailcard.has-draft .mc-head{cursor:pointer}.mc-head.nodraft{opacity:.9}' +
	'.mc-dot{width:9px;height:9px;border-radius:50%;background:var(--baseline);display:inline-block}' +
	'.mc-dot.hi{background:var(--critical);box-shadow:0 0 0 3px color-mix(in srgb,var(--critical) 25%,transparent)}' +
	'.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.72rem;font-weight:700;white-space:nowrap}' +
	'.pill.rel{background:var(--series-1);color:#fff}.pill.info{background:var(--grid);color:var(--text-secondary)}' +
	'.mc-box{font-size:.72rem;font-weight:700;color:var(--brand-teal);background:color-mix(in srgb,var(--brand-teal) 12%,transparent);' +
	'padding:2px 8px;border-radius:6px;white-space:nowrap}' +
	'.mc-sender{font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}' +
	'.mc-subj{color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;grid-column:1/-1}' +
	'a.mc-subj{color:var(--blue-500,#2490ef);text-decoration:none}a.mc-subj:hover{text-decoration:underline}' +
	'.mc-reason{grid-column:1/-1;font-size:.86rem;color:var(--text-secondary)}' +
	'.mc-actions{grid-column:1/-1;display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:2px}' +
	'.mc-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:999px;' +
	'font-size:.72rem;font-weight:650;white-space:nowrap}' +
	'.mc-badge.replied{background:color-mix(in srgb,var(--green-500,#28a745) 15%,transparent);color:var(--green-500,#28a745)}' +
	'.mc-time{font-size:.72rem;color:var(--text-secondary);white-space:nowrap}' +
	'.mc-badge.assignee{background:color-mix(in srgb,var(--brand-teal) 15%,transparent);color:var(--brand-teal);cursor:pointer}' +
	'.mc-assign-btn{font-size:.72rem;padding:2px 9px;border-radius:999px;border:1px dashed var(--border);' +
	'background:transparent;color:var(--text-secondary);cursor:pointer}' +
	'.mc-assign-btn:hover{border-color:var(--brand-teal);color:var(--brand-teal)}' +
	'.mc-chev{position:absolute;right:12px;color:var(--muted);transition:transform .15s}' +
	'.mailcard.open .mc-chev{transform:rotate(180deg)}' +
	'.mc-draft{padding:0 12px 12px}.mc-draft-lbl{font-size:.78rem;color:var(--muted);margin:8px 0 6px}' +
	'.preview-text{white-space:pre-wrap;background:var(--surface-1);border:1px dashed var(--border);border-radius:8px;' +
	'padding:10px;font-size:.85rem;color:var(--text-secondary);max-height:180px;overflow-y:auto;margin:0}' +
	'.draft-text{white-space:pre-wrap;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;' +
	'padding:12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.83rem;margin:0 0 8px;overflow-x:auto}' +
	'.copybtn{border:1px solid var(--brand-teal);background:transparent;color:var(--brand-teal);border-radius:8px;' +
	'padding:6px 12px;font-size:.82rem;font-weight:700;cursor:pointer}.copybtn:hover{background:var(--brand-teal);color:#fff}' +
	'.dot-hi{color:var(--critical);font-weight:700}' +
	'@media (min-width:680px){.mc-head{grid-template-columns:auto auto auto minmax(150px,220px) 2fr;padding-right:30px}' +
	'.mc-subj{grid-column:auto}.mc-reason{grid-column:1/-1}}' +
	'.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}' +
	'.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px}' +
	'.tile .k{color:var(--text-secondary);font-size:.82rem;margin:0 0 6px}.tile .v{font-size:1.7rem;font-weight:680}' +
	'.tile .m{font-size:.82rem;color:var(--muted);margin-top:4px}' +
	'.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:.82rem;font-weight:600;color:#fff}' +
	'.pcb-root figure{margin:0}.pcb-root figcaption{font-weight:600;margin-bottom:8px;font-size:.98rem}' +
	'.meter-wrap{margin-top:10px}.meter{position:relative;height:26px;border-radius:8px;background:var(--grid);overflow:hidden}' +
	'.meter .fill{height:100%;border-radius:8px 0 0 8px}.meter .proj{height:100%;opacity:.45}.meter-row{display:flex;height:100%}' +
	'.meter .mk{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--text-primary)}' +
	'.meter .mk.costs{background:var(--critical);width:3px;box-shadow:0 0 0 1px var(--surface-1)}' +
	'.mlbl-row{position:relative;height:18px;font-size:.8rem;color:var(--text-secondary)}' +
	'.mlbl-row.top{margin-bottom:4px}.mlbl-row.bot{margin-top:6px}' +
	'.mlbl{position:absolute;white-space:nowrap;font-weight:650}' +
	'.mlbl .costs-lbl{color:var(--critical)}' +
	'.mlbl .target-lbl{color:var(--text-primary)}' +
	'.pcb-root figcaption.bar2{margin-top:26px}' +
	'.vcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;margin-top:16px}' +
	'.vcards .card{margin-top:0}' +
	'.vcard figcaption{text-align:center}' +
	'.vcard .vrow{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:7px 0;border-bottom:1px solid var(--border)}' +
	'.vcard .vrow:last-child{border-bottom:0;padding-bottom:0}' +
	'.vcard .vk{font-size:.84rem;color:var(--text-secondary)}' +
	'.vcard .vhint{font-style:normal;color:var(--muted);font-size:.76rem}' +
	'.vcard .vv{font-weight:680;font-size:1.15rem;white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}' +
	'.vcard .vdelta{font-size:.8rem;font-weight:650}' +
	'.rev-tiles .tile.hero{grid-column:span 2}' +
	'.rev-tiles .tile.hero .v{font-size:2.4rem}' +
	'.rev-tiles .tile:not(.hero) .v{font-size:1.35rem}' +
	'.rev-tiles .tile:not(.hero) .k,.rev-tiles .tile:not(.hero) .m{font-size:.78rem}' +
	'.meter-verdict{font-size:.86rem;margin-top:8px;font-weight:650}' +
	'.cov-track{position:relative;display:flex;height:30px;border-radius:8px;overflow:hidden;background:var(--grid);gap:2px}' +
	'.cov-track .seg{height:100%}.cov-target{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--text-primary)}' +
	'.cov-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.82rem;color:var(--text-secondary);margin-top:10px}' +
	'.cov-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}' +
	'.cov-verdict{font-size:.9rem;margin:8px 0 0;color:var(--text-secondary)}' +
	'.cov-legend .lg{white-space:nowrap}.cov-sum{color:var(--text-secondary)}' +
	'.tips{margin:0;padding:0;list-style:none}.tips li{display:flex;gap:14px;align-items:baseline;padding:10px 0;border-top:1px solid var(--border)}' +
	'.tips li:first-child{border-top:0}.tip-eur{font-weight:680;color:var(--series-2);min-width:96px;text-align:right;font-variant-numeric:tabular-nums}' +
	'.tip-body{display:flex;flex-direction:column}.tip-detail{color:var(--text-secondary);font-size:.88rem}' +
	'.tbl{width:100%;border-collapse:collapse;font-size:.9rem}.tbl th,.tbl td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}' +
	'.tbl th{color:var(--text-secondary);font-weight:600}.tbl .num{text-align:right;font-variant-numeric:tabular-nums}' +
	'.tbl a{color:var(--blue-500,#2490ef);text-decoration:none;font-weight:600}.tbl a:hover{text-decoration:underline}' +
	'.tbl tfoot td{font-weight:650;border-top:2px solid var(--baseline)}' +
	'.tbl tr.late{background:color-mix(in srgb,var(--critical) 8%,transparent)}' +
	'.tbl tr.late .exp{color:var(--critical);font-weight:700}' +
	'.po-toggle{border:1px solid var(--border);background:var(--plane);color:var(--text-secondary);' +
	'border-radius:999px;padding:2px 10px;font-size:.76rem;font-weight:650;cursor:pointer;white-space:nowrap}' +
	'.po-toggle:hover{border-color:var(--brand-teal);color:var(--brand-teal)}' +
	'.pill.unlock{background:var(--series-2);color:#fff;margin-left:4px}' +
	'.unlock-tag{font-size:.9rem}' +
	'.po-detail td{background:var(--plane)}' +
	'.po-items{display:flex;flex-direction:column;gap:6px}' +
	'.po-item{display:flex;gap:12px;flex-wrap:wrap;align-items:baseline;justify-content:space-between}' +
	'.pi-name{font-weight:650;font-size:.86rem}' +
	'.pi-wos{display:flex;gap:8px;flex-wrap:wrap;font-size:.84rem}' +
	'.wo-chip{background:var(--surface-1);border:1px solid var(--border);border-radius:6px;padding:1px 7px;white-space:nowrap}' +
	'.wo-chip.missing{border-color:var(--critical);border-style:dashed}' +
	'.wo-list{display:inline-flex;gap:6px;flex-wrap:wrap}' +
	'.tbl th.sortable{cursor:pointer;user-select:none;white-space:nowrap}' +
	'.tbl th.sortable:hover{color:var(--brand-teal)}' +
	'.tbl th.sorted{color:var(--brand-teal)}' +
	'.sort-ind{opacity:.55;margin-left:4px;font-size:.72rem}' +
	'.tbl th.sorted .sort-ind{opacity:1}' +
	'.prod-tbl{font-size:.86rem}.prod-tbl td{vertical-align:top}' +
	'.assignee-btn{border:1px dashed var(--border);background:transparent;color:var(--muted);' +
	'border-radius:999px;min-width:30px;padding:2px 8px;font-size:.78rem;font-weight:700;cursor:pointer}' +
	'.assignee-btn:hover{border-color:var(--brand-teal);color:var(--brand-teal)}' +
	'.assignee-btn.set{border-style:solid;background:color-mix(in srgb,var(--brand-teal) 12%,transparent);' +
	'color:var(--brand-teal)}' +
	'.note-btn{border:1px dashed var(--border);background:transparent;color:var(--text-primary);' +
	'border-radius:8px;padding:3px 8px;font-size:.8rem;cursor:pointer;text-align:left;max-width:220px}' +
	'.note-btn:hover{border-color:var(--brand-teal);border-style:solid}' +
	'.ekt-link{font-weight:650;white-space:nowrap}' +
	'.hold-btn{border:1px solid var(--border);background:var(--surface-1);color:var(--text-secondary);' +
	'border-radius:999px;padding:3px 10px;font-size:.76rem;font-weight:650;cursor:pointer;white-space:nowrap}' +
	'.hold-btn:hover{border-color:var(--warning);color:var(--warning)}' +
	'.hold-btn.on{background:var(--warning);border-color:transparent;color:#3a2c00}' +
	'.hold-btn.on:hover{filter:brightness(1.06);color:#3a2c00}' +
	// Gesperrte Zeilen treten zurueck, bleiben aber lesbar — sie sind nicht
	// erledigt, nur gerade nicht dran.
	'.tbl tr.held{background:color-mix(in srgb,var(--warning) 10%,transparent)}' +
	'.tbl tr.held td:not(.hold-cell){opacity:.62}' +
	'.wo-chip.held{border-color:var(--warning);border-style:dashed}' +
	'.followup{font-weight:650;color:var(--brand-teal);white-space:nowrap}' +
	'.fu-mark{cursor:help}' +
	'.pill{background:var(--grid);color:var(--text-secondary)}' +
	// Schmalere Spalten in der Liefertermin-Liste: Kundenname 25 % schmaler
	// (240 -> 180 px) und bei Bedarf gekürzt (voller Name im Tooltip),
	// Produktionsauftrag 40 % schmaler (200 -> 120 px), Kürzel brechen um.
	'.tbl td.col-customer,.tbl th.col-customer{max-width:180px;overflow:hidden;' +
	'text-overflow:ellipsis;white-space:nowrap}' +
	'.tbl td.col-wo,.tbl th.col-wo{max-width:120px}' +
	'.tbl td.col-wo .wo-list{flex-wrap:wrap}' +
	// Ausgehende Pakete: Lieferschein 30 % schmaler (160 -> 112 px),
	// Kunde 40 % schmaler (240 -> 144 px, langer Name gekürzt, voll im Tooltip).
	'.tbl td.col-dn,.tbl th.col-dn{max-width:112px;white-space:nowrap}' +
	'.tbl td.col-dn-customer,.tbl th.col-dn-customer{max-width:144px;overflow:hidden;' +
	'text-overflow:ellipsis;white-space:nowrap}' +
	// Kachel mit zwei Beträgen nebeneinander.
	'.split-vals{display:flex;gap:18px;flex-wrap:wrap;margin-top:2px}' +
	'.split-vals .sv{display:flex;flex-direction:column}' +
	'.split-vals .sv-v{font-size:1.35rem;font-weight:680;font-variant-numeric:tabular-nums}' +
	'.split-vals .sv-k{font-size:.74rem;color:var(--muted)}' +
	'.mat-toggle{display:flex;align-items:center;gap:6px;border:0;background:transparent;padding:0;' +
	'cursor:pointer;font-size:.8rem;color:var(--text-secondary);white-space:nowrap;text-align:left}' +
	'.mat-toggle:hover .chev{color:var(--brand-teal)}' +
	'.mat-bar{display:inline-block;width:54px;height:7px;border-radius:999px;background:var(--grid);overflow:hidden;flex:0 0 auto}' +
	'.mat-bar i{display:block;height:100%;border-radius:999px}' +
	'.mat-detail{display:flex;flex-direction:column;gap:3px;margin-top:6px;max-height:280px;overflow-y:auto}' +
	// Rahmenfarbe = Zustand der Position: gruen vorhanden, gelb im Zulauf,
	// rot gestrichelt nicht bestellt.
	'.mat-pos{display:grid;grid-template-columns:minmax(90px,auto) auto 1fr;gap:8px;align-items:baseline;' +
	'border:1px solid var(--border);border-left-width:3px;border-radius:6px;padding:2px 8px;font-size:.78rem;' +
	'background:var(--surface-1)}' +
	'.mat-pos.ok{border-color:var(--good)}' +
	'.mat-pos.wait{border-color:var(--series-3)}' +
	'.mat-pos.missing{border-color:var(--critical);border-style:dashed;border-left-style:solid}' +
	'.mat-pos .mp-code{font-weight:650;white-space:nowrap}' +
	'.mat-pos .mp-qty{color:var(--text-secondary);white-space:nowrap;font-variant-numeric:tabular-nums}' +
	'.mat-pos .mp-info{color:var(--text-secondary)}' +
	'.note-date{font-weight:650;color:var(--brand-teal);white-space:nowrap}' +
	'.note-txt{display:block;color:var(--text-secondary);font-size:.78rem;white-space:normal}' +
	'.pcb-root .muted{color:var(--muted)}.pcb-root .foot{color:var(--muted);font-size:.78rem;margin-top:18px}' +
	// Bewusst kein vollflächiges Overlay: der Refresh-Status ist global (alle Nutzer
	// sehen denselben Stand), aber niemand soll deshalb blockiert werden — nur ein
	// kleiner, nicht-interaktionshemmender Hinweis oben rechts, Rest der Seite bleibt
	// normal bedienbar (Tabs wechseln, Mails filtern, ...) während im Hintergrund
	// aktualisiert wird.
	'.pcb-root .overlay{position:fixed;top:74px;right:20px;background:var(--surface-1);' +
	'border:1px solid var(--border);border-radius:12px;padding:10px 16px;box-shadow:0 6px 20px rgba(0,0,0,.18);' +
	'display:none;flex-direction:row;align-items:center;gap:10px;z-index:1050;max-width:280px;pointer-events:none}' +
	'.pcb-root .overlay.show{display:flex}.pcb-root .overlay .ov-text-wrap{display:flex;flex-direction:column}' +
	'.pcb-root .overlay .ov-txt{font-weight:700;color:var(--brand-teal);font-size:.88rem}' +
	'.pcb-root .overlay .ov-sub{color:var(--text-secondary);font-size:.74rem}' +
	'.pcb-root .toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(20px);background:var(--text-primary);' +
	'color:var(--surface-1);padding:10px 18px;border-radius:10px;font-size:.86rem;font-weight:600;opacity:0;' +
	'transition:all .2s;z-index:1060;pointer-events:none}.pcb-root .toast.show{opacity:1;transform:translateX(-50%) translateY(0)}' +
	'@media (prefers-reduced-motion:reduce){.pcb-logo.pulsing,.pcb-logo.pulsing .pcb-seg,.pcb-logo.pulsing .pcb-disc{animation:none}}';
