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
	this.metrics = null;

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
		'<div><h1 id="pcb-h1">Team-Board</h1><div class="tag">der/die/das Sekretär/-in</div>' +
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
		'<button data-tab="todo">📋 ToDo</button>' +
		'<button data-tab="revenue">📊 Umsatz</button>' +
		'<button data-tab="billing">🧾 Abrechnung</button>' +
		'<button data-tab="costs">💸 Kosten</button>' +
		'<button data-tab="assign">👤 Zuweisungen</button>' +
		'</div>' +
		'<div class="tab-panel active" id="pcb-tab-mail"><p class="muted">Lade Daten …</p></div>' +
		'<div class="tab-panel" id="pcb-tab-todo"></div>' +
		'<div class="tab-panel" id="pcb-tab-revenue"></div>' +
		'<div class="tab-panel" id="pcb-tab-billing"></div>' +
		'<div class="tab-panel" id="pcb-tab-costs"></div>' +
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
	var stand = m.generated_at ? frappe.datetime.str_to_user(m.generated_at) : '—';
	var duration = m.refresh_seconds ? ' (' + m.refresh_seconds + ' s)' : '';
	var next = ' · nächster Refresh in ' + this.nextRefreshIn();
	this.$root.find('#pcb-stand').text('Stand ' + stand + duration + next);
	this.$root.find('#pcb-tab-mail').html(this.mailTabHtml(m));
	this.$root.find('#pcb-tab-todo').html(this.todoTabHtml(m));
	this.$root.find('#pcb-tab-revenue').html(this.revenueTabHtml(m));
	this.$root.find('#pcb-tab-billing').html(this.billingTabHtml(m));
	this.$root.find('#pcb-tab-costs').html(this.costsTabHtml(m));
	this.bindMailInteractions();
};

PCBBoard.prototype.todoTabHtml = function (m) {
	var self = this;
	var t = m.todo || {};
	var overdue = t.overdue || [];
	var week = t.due_this_week || [];

	function soLink(name) {
		return '<a href="/app/sales-order/' + encodeURIComponent(name) + '" target="_blank">' +
			self.esc(name) + '</a>';
	}
	function table(rows, withDelay) {
		var body = rows.map(function (r) {
			var delay = '';
			if (withDelay) {
				delay = '<td class="num" style="color:var(--critical)">' +
					(r.days_overdue > 0 ? r.days_overdue + ' Tag(e)' : 'heute') + '</td>';
			}
			return '<tr><td>' + soLink(r.name) + '</td><td>' + self.esc(r.customer || '') + '</td>' +
				'<td>' + self.esc(frappe.datetime.str_to_user(r.delivery_date)) + '</td>' + delay +
				'<td class="num">' + self.eur(r.net_open) + '</td></tr>';
		}).join('');
		return '<table class="tbl"><thead><tr><th>Auftrag</th><th>Kunde</th><th>Liefertermin</th>' +
			(withDelay ? '<th class="num">Verzug</th>' : '') +
			'<th class="num">Offen (netto)</th></tr></thead><tbody>' + body + '</tbody></table>';
	}

	var trend = '';
	if (t.trend) {
		var dn = t.trend.delta_net || 0;
		var better = dn < 0;
		var arrow = dn === 0 ? '▶' : (better ? '▼' : '▲');
		var color = dn === 0 ? 'var(--text-secondary)' : (better ? 'var(--good)' : 'var(--critical)');
		var sign = dn > 0 ? '+' : (dn < 0 ? '−' : '±');
		trend = ' <span style="color:' + color + ';font-weight:650" title="Vergleich mit Stand vom ' +
			self.esc(frappe.datetime.str_to_user(t.trend.prev_date)) + ' (' + self.eur(t.trend.prev_net) + ')">' +
			arrow + ' ' + sign + self.eur(Math.abs(dn)) + ' ggü. Vorwoche</span>';
	}
	var secOverdue = '<section class="card"><div class="sec-h"><h2>🔴 Liefertermin heute oder überfällig</h2>' +
		'<span class="muted">' + overdue.length + ' Auftrag/Aufträge · ' + self.eur(t.overdue_net || 0) + ' offen' + trend + '</span></div>' +
		(overdue.length ? table(overdue, true)
			: '<p class="muted">Nichts überfällig — alles im Plan. ✅</p>') +
		'</section>';
	var secWeek = '<section class="card"><div class="sec-h"><h2>🟡 Diese Woche fällig</h2>' +
		'<span class="muted">sollte diese Woche fertig werden · ' + self.eur(t.due_this_week_net || 0) + ' offen</span></div>' +
		(week.length ? table(week, false)
			: '<p class="muted">Keine weiteren Liefertermine in dieser Woche.</p>') +
		'</section>';
	return secOverdue + secWeek;
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
		this.productMarginsHtml(m) + this.profitHistoryHtml(m);
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
		var cost = p.cost == null ? '<span class="muted">—</span>' : self.eur(p.cost);
		var margin, marginPct;
		if (p.margin == null) {
			margin = '<span class="muted">—</span>';
			marginPct = '<span class="muted">kein EK-Preis</span>';
		} else {
			var col = p.margin >= 0 ? 'var(--good)' : 'var(--critical)';
			margin = '<span style="color:' + col + ';font-weight:650">' + self.eur(p.margin) + '</span>';
			marginPct = '<span style="color:' + col + '">' + self.pct(p.margin_pct) + '</span>';
		}
		return '<tr><td>' + self.esc(p.item_name || p.item_code) + '</td>' +
			'<td class="num">' + self.eur(p.revenue) + '</td>' +
			'<td class="num">' + cost + '</td>' +
			'<td class="num">' + margin + '</td>' +
			'<td class="num">' + marginPct + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Deckungsbeitrag Top-Produkte (Monat)</figcaption>' +
		'<table class="tbl"><thead><tr><th>Produkt</th><th class="num">Umsatz</th>' +
		'<th class="num">Wareneinsatz</th><th class="num">DB</th><th class="num">DB %</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Wareneinsatz = verkaufte Menge × ' +
		'letzter Einkaufspreis des Artikels (ERPNext „Item"). Ohne hinterlegten Einkaufspreis ' +
		'(z. B. Eigenfertigung/Dienstleistung) bleibt die Marge leer.</p></section>';
};

PCBBoard.prototype.topPurchasesHtml = function (m) {
	var self = this;
	var items = m.top_purchases || [];
	if (!items.length) {
		return '<section class="card"><figcaption>Top 5 Einkäufe (Monat)</figcaption>' +
			'<p class="muted">Noch keine Wareneingangspositionen in diesem Monat.</p></section>';
	}
	var rows = items.map(function (p, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td>' + self.esc(p.item_name || p.item_code) + '</td>' +
			'<td class="num">' + self.eur(p.net_total) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Einkäufe (Monat, Netto-Warenwert)</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Artikel</th><th class="num">Warenwert</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.profitHistoryHtml = function (m) {
	var self = this;
	var ph = m.profit_history || {};
	var months = ph.months || [];
	if (!months.length) {
		return '';
	}
	var names = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
	var cum = 0;
	var rows = months.map(function (r) {
		cum += r.profit;
		var lbl = names[parseInt(r.month.slice(5), 10) - 1] || r.month;
		if (r.is_current) lbl += ' (läuft)';
		function colored(v) {
			return '<td class="num" style="color:' + (v >= 0 ? 'var(--good)' : 'var(--critical)') +
				';font-weight:650">' + self.eur(v) + '</td>';
		}
		return '<tr' + (r.is_current ? ' style="opacity:.75"' : '') + '><td>' + self.esc(lbl) + '</td>' +
			'<td class="num">' + self.eur(r.revenue) + '</td>' +
			'<td class="num">' + self.eur(r.goods_receipts) + '</td>' +
			'<td class="num">' + self.eur(r.fixed_costs) + '</td>' +
			colored(r.profit) + colored(cum) + '</tr>';
	}).join('');
	return '<section class="card"><figcaption>Gewinn/Verlust je Monat (' +
		self.esc((m.as_of || '').slice(0, 4)) + ')</figcaption>' +
		'<table class="tbl"><thead><tr><th>Monat</th><th class="num">Umsatz</th>' +
		'<th class="num">Wareneingänge</th><th class="num">Fixkosten</th>' +
		'<th class="num">Gewinn/Verlust</th><th class="num">kumuliert</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table>' +
		'<p class="muted" style="font-size:.82rem;margin:8px 0 0">Annahme: Personalkosten und Miete ' +
		'gleichbleibend (' + self.eur(ph.fixed_costs_monthly || 0) + '/Monat, PCB Board Settings); ' +
		'variable Kosten = im jeweiligen Monat gebuchte Wareneingänge.</p></section>';
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

	var chips = '<button class="chip active" data-mb="all">Alle</button>';
	boxes.forEach(function (b) {
		chips += '<button class="chip" data-mb="' + self.esc(b.name) + '">' +
			self.esc(self.shortBox(b.name)) + ' <span class="chip-n">' + b.total + '</span></button>';
	});

	var tiles =
		'<div class="mini" id="pcb-mail-counts">' +
		'<div class="b"><div class="v" data-count="total">' + (mail.total || 0) + '</div><div class="k">Neu (' + winlbl + ')</div></div>' +
		'<div class="b"><div class="v" data-count="relevant" style="color:var(--series-1)">' + (mail.relevant || 0) + '</div><div class="k">Zu beantworten</div></div>' +
		'<div class="b"><div class="v" data-count="info">' + (mail.info || 0) + '</div><div class="k">Nur Info</div></div>' +
		'<div class="b"><div class="v" data-count="high" style="color:var(--critical)">' + (mail.high_priority || 0) + '</div><div class="k">Dringend</div></div>' +
		'</div>';

	var controls =
		'<div class="mailctl"><div class="segbtns" id="pcb-cat-filter">' +
		'<button class="active" data-cat="all">Alle</button>' +
		'<button data-cat="relevant">Zu beantworten</button>' +
		'<button data-cat="high">Dringend</button>' +
		'<button data-cat="info">Info</button>' +
		'</div><input type="search" id="pcb-mail-search" placeholder="Suche: Absender, Betreff …"></div>';

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
		var searchTxt = (sender + ' ' + subj + ' ' + reason).toLowerCase();
		var dot = prio === 'high' ? '<span class="mc-dot hi" title="dringend"></span>' : '<span class="mc-dot"></span>';
		var pill = rel ? '<span class="pill rel">Antwort</span>' : '<span class="pill info">Info</span>';
		var can = !!draft;
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
		var head = '<div class="mc-head' + (can ? '' : ' nodraft') + '">' + dot + pill +
			'<span class="mc-box">' + self.esc(self.shortBox(i.mailbox)) + '</span>' +
			'<span class="mc-sender">' + self.esc(sender) + '</span>' +
			subjHtml +
			'<span class="mc-reason">' + self.esc(reason) + '</span>' + actions + chev + '</div>';
		var draftBlock = '';
		if (can) {
			draftBlock = '<div class="mc-draft" hidden><div class="mc-draft-lbl">Antwortvorschlag ' +
				'(zum Kopieren – wird nicht automatisch gesendet):</div>' +
				'<pre class="draft-text">' + self.esc(draft) + '</pre>' +
				'<button class="copybtn" type="button">📋 Kopieren</button></div>';
		}
		return '<div class="mailcard' + (can ? ' has-draft' : '') + '" data-mb="' + self.esc(i.mailbox) + '" ' +
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
		self.q = $(this).val().toLowerCase().trim();
		applyFilter();
	});
	root.find('.mailcard.has-draft .mc-head').on('click', function () {
		var $card = $(this).parent();
		var $d = $card.find('.mc-draft');
		$card.toggleClass('open');
		$d.prop('hidden', !$card.hasClass('open'));
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
	var scaleMax = Math.max(m.target, fc.forecast_high, costsTotal) || 1;
	var mtdW = (fc.mtd / scaleMax) * 100;
	var projW = (Math.max(fc.forecast - fc.mtd, 0) / scaleMax) * 100;
	var targetPos = (m.target / scaleMax) * 100;
	var costsPos = (costsTotal / scaleMax) * 100;

	var profitMtd = fc.mtd - costsTotal;
	var profitForecast = fc.forecast - costsTotal;

	var tiles =
		'<div class="tiles">' +
		'<div class="tile"><p class="k">Ist-Umsatz (Netto)</p><div class="v">' + self.eur(fc.mtd) + '</div>' +
		'<div class="m">' + fc.bd_elapsed + ' von ' + fc.bd_total + ' Werktagen</div></div>' +
		'<div class="tile"><p class="k">Prognose Monatsende</p><div class="v">' + self.eur(fc.forecast) + '</div>' +
		'<div class="m"><span class="badge" style="background:' + st[0] + '">' + st[2] + ' ' + st[1] + ' · ' + self.pct(fc.attainment_pct) + '</span></div></div>' +
		'<div class="tile"><p class="k">' + (fc.gap > 0 ? 'Lücke zum Ziel' : 'Über Ziel') + '</p><div class="v">' + self.eur(Math.abs(fc.gap)) + '</div>' +
		'<div class="m">Ziel ' + self.eur(m.target) + '</div></div>' +
		'<div class="tile"><p class="k">Nötig je Restwerktag</p><div class="v">' + self.eur(fc.required_daily) + '</div>' +
		'<div class="m">an ' + fc.bd_remaining + ' Werktagen</div></div>' +
		'<div class="tile"><p class="k">Gewinn/Verlust (Prognose)</p>' +
		'<div class="v" style="color:' + (profitForecast >= 0 ? 'var(--good)' : 'var(--critical)') + '">' +
		(profitForecast >= 0 ? '+' : '−') + self.eur(Math.abs(profitForecast)) + '</div>' +
		'<div class="m">nach Abzug Gesamtkosten ' + self.eur(costsTotal) + '</div></div>' +
		'</div>';

	var verdictText = profitMtd >= 0
		? '✅ Kosten bereits gedeckt — aktuell ' + self.eur(profitMtd) + ' im Plus.'
		: '🔻 Noch ' + self.eur(Math.abs(profitMtd)) + ' bis zur Kostendeckung (Ist).';

	var meter =
		'<section class="card"><figcaption>Zielerreichung</figcaption><div class="meter-wrap">' +
		'<div class="meter"><div class="meter-row">' +
		'<div class="fill" style="width:' + mtdW.toFixed(2) + '%;background:var(--series-1)"></div>' +
		'<div class="proj" style="width:' + projW.toFixed(2) + '%;background:' + st[0] + '"></div>' +
		'</div><div class="mk" style="left:' + targetPos.toFixed(2) + '%" title="Umsatzziel"></div>' +
		'<div class="mk costs" style="left:' + costsPos.toFixed(2) + '%" title="Gesamtkosten (Kostendeckung)"></div></div>' +
		'<div class="meter-labels"><span>Ist ' + self.eur(fc.mtd) + '</span><span>Prognose ' + self.eur(fc.forecast) + '</span>' +
		'<span>Ziel ' + self.eur(m.target) + '</span><span class="costs-lbl">Kosten ' + self.eur(costsTotal) + '</span></div>' +
		'<p class="meter-verdict" style="color:' + (profitMtd >= 0 ? 'var(--good)' : 'var(--critical)') + '">' +
		verdictText + '</p></div></section>';

	var topProducts = this.topProductsHtml(m);
	var prevYear = this.prevYearHtml(m);
	var topCustomers = this.topCustomersHtml(m);
	var coverage = this.coverageBarHtml(m);
	var tips = this.tipsHtml(m);

	return tiles + meter + prevYear + topProducts + topCustomers + coverage + tips;
};

PCBBoard.prototype.prevYearHtml = function (m) {
	var self = this;
	var py = m.prev_year;
	var fc = m.forecast || {};
	if (!py || (!py.total && !py.mtd_same_day)) {
		return '';
	}
	var names = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
		'August', 'September', 'Oktober', 'November', 'Dezember'];
	var monthName = names[(py.month || 1) - 1] || '';
	var deltaHtml = '';
	if (py.mtd_same_day > 0) {
		var delta = (fc.mtd || 0) - py.mtd_same_day;
		var pct = Math.round((delta / py.mtd_same_day) * 100);
		var up = delta >= 0;
		deltaHtml = ' <span style="color:' + (up ? 'var(--good)' : 'var(--critical)') + ';font-weight:650">' +
			(up ? '▲ +' : '▼ −') + Math.abs(pct) + ' %</span> ggü. Vorjahr zum selben Tag';
	}
	return '<section class="card"><figcaption>Vorjahresvergleich (Saisonalität)</figcaption>' +
		'<div class="tiles">' +
		'<div class="tile"><p class="k">' + self.esc(monthName + ' ' + py.year) + ' gesamt</p>' +
		'<div class="v">' + self.eur(py.total) + '</div>' +
		'<div class="m">kompletter Vorjahresmonat</div></div>' +
		'<div class="tile"><p class="k">' + self.esc(monthName + ' ' + py.year) + ' bis zum selben Tag</p>' +
		'<div class="v">' + self.eur(py.mtd_same_day) + '</div>' +
		'<div class="m">Vergleichsbasis für den Ist-Umsatz</div></div>' +
		'<div class="tile"><p class="k">Ist jetzt</p>' +
		'<div class="v">' + self.eur(fc.mtd) + '</div>' +
		'<div class="m">' + (deltaHtml || 'kein Vorjahres-Vergleichswert') + '</div></div>' +
		'</div></section>';
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
	return '<section class="card"><figcaption>Top 5 Kunden (Monat, Netto-Umsatz — Klumpenrisiko im Blick behalten)</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Kunde</th><th class="num">Umsatz</th>' +
		'<th class="num">Anteil</th></tr></thead><tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.topProductsHtml = function (m) {
	var self = this;
	var items = m.top_products || [];
	if (!items.length) {
		return '<section class="card"><figcaption>Top 5 Produkte (Monat)</figcaption>' +
			'<p class="muted">Noch keine Rechnungspositionen in diesem Monat.</p></section>';
	}
	var rows = items.map(function (p, idx) {
		return '<tr><td>' + (idx + 1) + '</td><td>' + self.esc(p.item_name || p.item_code) + '</td>' +
			'<td class="num">' + self.eur(p.net_total) + '</td></tr>';
	}).join('');
	return '<section class="card"><figcaption>Top 5 Produkte (Monat, Netto-Umsatz)</figcaption>' +
		'<table class="tbl"><thead><tr><th>#</th><th>Produkt</th><th class="num">Umsatz</th></tr></thead>' +
		'<tbody>' + rows + '</tbody></table></section>';
};

PCBBoard.prototype.coverageBarHtml = function (m) {
	var self = this;
	var fc = m.forecast, pl = m.pipeline, target = m.target;
	var scaleMax = Math.max(target, pl.coverage_after_forecast) * 1.02 || 1;
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
	return '<figure class="card"><figcaption>Zieldeckung inkl. Pipeline</figcaption>' +
		'<div class="cov-track">' + rects +
		'<div class="cov-target" style="left:' + ((target / scaleMax) * 100).toFixed(2) + '%"></div></div>' +
		'<div class="cov-legend">' + legend + '</div><p class="cov-verdict">' + self.esc(verdict) + '</p></figure>';
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

PCBBoard.prototype.billingGroupHtml = function (title, rows, total) {
	var self = this;
	var methodLabel = { ups: 'UPS', fallback: 'geschätzt', none: '—' };
	if (!rows || !rows.length) {
		return '<figcaption>' + title + '</figcaption><p class="muted">—</p>';
	}
	var body = rows
		.map(function (r) {
			var age = r.age_days;
			var alt = age != null && age > 60 ? ' <span class="dot-hi">alt</span>' : '';
			return '<tr><td><a href="/app/delivery-note/' + encodeURIComponent(r.name) + '" target="_blank">' + self.esc(r.name) + '</a></td><td>' + self.esc(r.customer || '') + '</td>' +
				'<td class="num">' + self.eur(r.net_open) + '</td>' +
				'<td>' + self.esc(r.delivered_date || r.posting_date || '—') + alt + '</td>' +
				'<td>' + (methodLabel[r.arrival_method] || '—') + '</td></tr>';
		})
		.join('');
	var tfoot = total != null
		? '<tfoot><tr><td colspan="2">Summe</td><td class="num">' + self.eur(total) + '</td><td colspan="2"></td></tr></tfoot>'
		: '';
	return '<figcaption>' + title + '</figcaption><table class="tbl"><thead><tr><th>Lieferschein</th>' +
		'<th>Kunde</th><th class="num">Netto</th><th>zugestellt / Datum</th><th>Quelle</th></tr></thead>' +
		'<tbody>' + body + '</tbody>' + tfoot + '</table>';
};

PCBBoard.prototype.billingTabHtml = function (m) {
	var b = m.billing;
	var ready = '<section class="card">' +
		this.billingGroupHtml('🧾 Jetzt abrechnen (Paket zugestellt) · ' + b.ready_count, b.ready, m.pipeline.ready_net) +
		'</section>';
	var transit = '<section class="card">' +
		this.billingGroupHtml('⏳ Unterwegs – nach Zustellung abrechnen · ' + b.in_transit.length, b.in_transit) +
		'</section>';
	var extra = '';
	if (b.stale && b.stale.length) {
		extra = '<section class="card">' +
			this.billingGroupHtml('⚠️ Alte offene Lieferscheine (>60 Tage) · ' + b.stale.length, b.stale) +
			'</section>';
	}
	return ready + transit + extra;
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
	'.mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px}' +
	'.mini .b{background:var(--plane);border:1px solid var(--border);border-radius:10px;padding:10px 12px}' +
	'.mini .b .v{font-size:1.45rem;font-weight:680}.mini .b .k{font-size:.78rem;color:var(--text-secondary)}' +
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
	'.mc-draft{padding:0 12px 12px}.mc-draft-lbl{font-size:.78rem;color:var(--muted);margin:2px 0 6px}' +
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
	'.meter-labels{display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-secondary);margin-top:6px}' +
	'.meter-labels .costs-lbl{color:var(--critical);font-weight:650}' +
	'.meter-verdict{font-size:.86rem;margin-top:8px;font-weight:650}' +
	'.cov-track{position:relative;display:flex;height:30px;border-radius:8px;overflow:hidden;background:var(--grid);gap:2px}' +
	'.cov-track .seg{height:100%}.cov-target{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--text-primary)}' +
	'.cov-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.82rem;color:var(--text-secondary);margin-top:10px}' +
	'.cov-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}' +
	'.cov-verdict{font-size:.9rem;margin:8px 0 0;color:var(--text-secondary)}' +
	'.tips{margin:0;padding:0;list-style:none}.tips li{display:flex;gap:14px;align-items:baseline;padding:10px 0;border-top:1px solid var(--border)}' +
	'.tips li:first-child{border-top:0}.tip-eur{font-weight:680;color:var(--series-2);min-width:96px;text-align:right;font-variant-numeric:tabular-nums}' +
	'.tip-body{display:flex;flex-direction:column}.tip-detail{color:var(--text-secondary);font-size:.88rem}' +
	'.tbl{width:100%;border-collapse:collapse;font-size:.9rem}.tbl th,.tbl td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}' +
	'.tbl th{color:var(--text-secondary);font-weight:600}.tbl .num{text-align:right;font-variant-numeric:tabular-nums}' +
	'.tbl a{color:var(--blue-500,#2490ef);text-decoration:none;font-weight:600}.tbl a:hover{text-decoration:underline}' +
	'.tbl tfoot td{font-weight:650;border-top:2px solid var(--baseline)}' +
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
