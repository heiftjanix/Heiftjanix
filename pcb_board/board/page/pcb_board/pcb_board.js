// Musterfirma Team-Board — native ERPNext Desk-Page.
// UI-Design 1:1 aus scripts/render_dashboard.py (Hauptrepo) nach JS portiert:
// PCB-Logo, Tabs (Posteingang/Umsatz/Abrechnung), Postfach-Chips, aufklappbare
// Mail-Karten mit Kopieren-Button, Meter/Chart/Coverage/Tips, Abrechnungstabellen.
// Unterschied zum Artifact-/Webapp-Board: Daten kommen per frappe.call() aus dieser
// ERPNext-Instanz selbst (siehe pcb_board/api.py), Login = normales ERPNext-Login.

frappe.pages['pcb-board'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Musterfirma Team-Board',
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
		'<div><h1>Musterfirma Team-Board</h1><div class="tag">Musterfirma-Sekretärin</div>' +
		'<div class="sub" id="pcb-stand">Lade …</div></div></div>' +
		'<div class="actions">' +
		'<span class="userchip">👤 ' + this.esc(frappe.session.user_fullname || frappe.session.user) + '</span>' +
		'<button class="btn primary" id="pcb-refresh" type="button">⟳ Live aktualisieren</button>' +
		'<button class="btn ghost" id="pcb-diagnose" type="button">🩺 Diagnose</button>' +
		'<button class="btn ghost" id="pcb-theme" type="button">◐ Theme</button>' +
		'</div></div>' +
		'<div class="tabs">' +
		'<button class="active" data-tab="mail">📥 Posteingang</button>' +
		'<button data-tab="revenue">📊 Umsatz</button>' +
		'<button data-tab="billing">🧾 Abrechnung</button>' +
		'</div>' +
		'<div class="tab-panel active" id="pcb-tab-mail"><p class="muted">Lade Daten …</p></div>' +
		'<div class="tab-panel" id="pcb-tab-revenue"></div>' +
		'<div class="tab-panel" id="pcb-tab-billing"></div>' +
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
		self.$root.toggleClass('pcb-dark');
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
	this.$root.find('#pcb-stand').text('Stand ' + stand);
	this.$root.find('#pcb-tab-mail').html(this.mailTabHtml(m));
	this.$root.find('#pcb-tab-revenue').html(this.revenueTabHtml(m));
	this.$root.find('#pcb-tab-billing').html(this.billingTabHtml(m));
	this.bindMailInteractions();
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

	var cards = items.map(function (i) {
		var rel = i.category === 'relevant';
		var prio = i.priority === 'high' ? 'high' : 'normal';
		var sender = i.sender_name || i.sender || '';
		var subj = i.subject || '';
		var reason = i.reason || '';
		var draft = (i.draft || '').trim();
		var searchTxt = (sender + ' ' + subj + ' ' + reason).toLowerCase();
		var dot = prio === 'high' ? '<span class="mc-dot hi" title="dringend"></span>' : '<span class="mc-dot"></span>';
		var pill = rel ? '<span class="pill rel">Antwort</span>' : '<span class="pill info">Info</span>';
		var can = !!draft;
		var chev = can ? '<span class="mc-chev">▾</span>' : '';
		var head = '<div class="mc-head' + (can ? '' : ' nodraft') + '">' + dot + pill +
			'<span class="mc-box">' + self.esc(self.shortBox(i.mailbox)) + '</span>' +
			'<span class="mc-sender">' + self.esc(sender) + '</span>' +
			'<span class="mc-subj">' + self.esc(subj) + '</span>' +
			'<span class="mc-reason">' + self.esc(reason) + '</span>' + chev + '</div>';
		var draftBlock = '';
		if (can) {
			draftBlock = '<div class="mc-draft" hidden><div class="mc-draft-lbl">Antwortvorschlag ' +
				'(zum Kopieren – wird nicht automatisch gesendet):</div>' +
				'<pre class="draft-text">' + self.esc(draft) + '</pre>' +
				'<button class="copybtn" type="button">📋 Kopieren</button></div>';
		}
		return '<div class="mailcard' + (can ? ' has-draft' : '') + '" data-mb="' + self.esc(i.mailbox) + '" ' +
			'data-cat="' + (rel ? 'relevant' : 'info') + '" data-prio="' + prio + '" ' +
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
	var scaleMax = Math.max(m.target, fc.forecast_high) || 1;
	var mtdW = (fc.mtd / scaleMax) * 100;
	var projW = (Math.max(fc.forecast - fc.mtd, 0) / scaleMax) * 100;
	var targetPos = (m.target / scaleMax) * 100;

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
		'</div>';

	var meter =
		'<section class="card"><figcaption>Zielerreichung</figcaption><div class="meter-wrap">' +
		'<div class="meter"><div class="meter-row">' +
		'<div class="fill" style="width:' + mtdW.toFixed(2) + '%;background:var(--series-1)"></div>' +
		'<div class="proj" style="width:' + projW.toFixed(2) + '%;background:' + st[0] + '"></div>' +
		'</div><div class="mk" style="left:' + targetPos.toFixed(2) + '%"></div></div>' +
		'<div class="meter-labels"><span>Ist ' + self.eur(fc.mtd) + '</span><span>Prognose ' + self.eur(fc.forecast) + '</span>' +
		'<span>Ziel ' + self.eur(m.target) + '</span></div></div></section>';

	var coverage = this.coverageBarHtml(m);
	var tips = this.tipsHtml(m);

	return tiles + meter + coverage + tips;
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
			return '<tr><td>' + self.esc(r.name) + '</td><td>' + self.esc(r.customer || '') + '</td>' +
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
	'.hd h1{font-size:1.3rem;line-height:1.1}.hd .tag{color:var(--brand-teal);font-weight:600;font-size:.82rem}' +
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
	'.sec-h{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}.sec-h h2{font-size:1.05rem}' +
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
	'.mc-reason{grid-column:1/-1;font-size:.86rem;color:var(--text-secondary)}' +
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
	'.meter-labels{display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-secondary);margin-top:6px}' +
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
