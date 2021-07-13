/* global MyAMS */

'use strict';


if (window.$ === undefined) {
	window.$ = MyAMS.$;
}


const zodbbrowser = {

	filterAll: function() {
		$('.filter').attr('checked', true);
		zodbbrowser.filterHistory(true);
	},

	filterNone: () => {
		$('.filter').attr('checked', false);
		zodbbrowser.filterHistory();
	},

	filterHistory: (showAll) => {
		const
			transactions = $('div.transaction'),
			filters = $('.filter'),
			filterMap = Array(),
			MAPPING_PREFIX = "map";

		for (let i = 0; i < filters.length; i++) {
			const filter = filters[i];
			if (filter.checked) {
				filterMap[MAPPING_PREFIX + filter.name] = filter.checked;
			}
		}

		for (let i = 0; i < transactions.length; i++) {
			const
				transaction = transactions[i],
				diffs = $(transaction).children('div.diff').children('div.diffitem');
			let n_hidden = 0;
			for (let j = 0; j < diffs.length; j++) {
				const id = $($(diffs[j]).children()[0]).text();
				if (MAPPING_PREFIX + id in filterMap || showAll) {
					$(diffs[j]).show();
				} else {
					$(diffs[j]).hide();
					n_hidden += 1;
				}
			}
			let hidden_text = null;
			if (n_hidden === 1) {
				hidden_text = '1 item hidden';
			} else if (n_hidden) {
				hidden_text = n_hidden + ' items hidden';
			}
			$(transaction).children('.filtered').remove();
			if (hidden_text) {
				$(transaction).append('<div class="filtered">' + hidden_text + '</div>');
			}
		}
	},

	collapseOrExpand: function (event) {
		// this is <div class="extender">
		// the following element is <div class="collapsible">
		const
			target = $(event.currentTarget),
			content = target.next(),
			icon = target.children('img');
		if (content.is(':hidden')) {
			$(icon).attr('src', $('#collapseImg').attr('src'));
			content.slideDown();
		} else {
			$(icon).attr('src', $('#expandImg').attr('src'));
			content.slideUp();
		}
	},

	hideItemsIfTooMany: function () {
		$('.items').each(function () {
			const
				expander = $(this).children('.expander')[0],
				content = $(this).children('.collapsible')[0];
			// items are formatted using <br /> so the heuristic is very
			// approximate.
			if (content.childNodes.length > 100 && !$(content).is(':hidden')) {
				const icon = $(expander).children('img');
				$(icon).attr('src', $('#expandImg').attr('src'));
				$(content).hide();
			}
		});
	},

	showGoTo: function () {
		$('#path').hide();
		$('#goto').show();
		$('#gotoInput').focus();
	},

	hideGoTo: function () {
		$('#goto').hide();
		$('#path').show();
		// Don't hide #pathError right away, this blur event might have been the
		// result of the user clicking on a link inside the #pathError text and
		// hiding it will prevent that link from getting activated.
		setTimeout(function () {
			$('#pathError').slideUp();
		}, 50);
	},

	ajaxErrorHandler: function (XMLHttpRequest, textStatus, errorThrown) {
		let errorMessage = "";
		if (textStatus === "parsererror") {
			errorMessage = "Server returned malformed data";
		} else if (textStatus === "error") {
			errorMessage = "Unknown error (maybe server is offline?)";
		} else if (textStatus === "timeout") {
			errorMessage = "Server timeout";
		} else if (textStatus === "notmodified") {
			errorMessage = "Server error (says resource not modified)";
		} else {
			errorMessage = "Unknown error";
		}

		errorMessage = '<span class="error"> ' + errorMessage + '</strong>';
		$('#pathError').html(errorMessage);
	},

	ajaxSuccessHandler: function (data, status) {
		if (data.url) {
			window.location = data.url;
			$('#pathError').text("Found.").slideDown().slideUp();
		} else if (data.error) {
			$('#pathError').text(data.error).show();
			if (data.partial_url) {
				$('#pathError').append(', would you like to ' +
									   '<a href="' + data.partial_url + '">' +
									   'go to ' + data.partial_path +
									   '</a>' +
									   ' instead?');
			}
		} else {
			$('#pathError').text(status).show();
		}
	},

	activateGoTo: function () {
		const
			path = $('#gotoInput').val(),
			api_url = 'zodbbrowser_path_to_oid';
		$('#pathError').text("Loading...").slideDown();
		$.ajax({
			url: api_url,
			dataType: 'json',
			data: "path=" + path,
			timeout: 7000,
			success: zodbbrowser.ajaxSuccessHandler,
			error: zodbbrowser.ajaxErrorHandler
		});
	},

	cancelRollback: function (e) {
		$('#confirmation').remove();
		$('div.transaction').removeClass('focus');
		$('input.rollbackbtn').show();
	},

	pressRollback: function (e) {
		e.preventDefault();
		zodbbrowser.cancelRollback();
		$(e.target).hide();
		const transaction_div = $(e.target).closest('div.transaction');
		transaction_div.addClass('focus');
		$('<div id="confirmation">' +
		    '<form action="" method="post">' +
		      '<div class="message">' +
		        'This is a dangerous operation that may break data integrity.' +
		        ' Are you really sure you want to do this?' +
		      '</div>' +
		      '<input type="BUTTON" value="Really revert to this state" onclick="zodbbrowser.doRollback()">' +
		      '<input type="BUTTON" value="Cancel" onclick="zodbbrowser.cancelRollback()">' +
		    '</form>' +
		  '</div>').appendTo(transaction_div);
	},

	doRollback: function () {
		const
			transaction_div = $('#confirmation').closest('div.transaction'),
			rollback_form = transaction_div.find('form.rollback');
		rollback_form.find('input[name="confirmed"]').val('1');
		rollback_form.submit();
	},

	initElement: function(element) {
		const css = $('.zodbbrowser').data('ams-zodbbrowser-css');
		MyAMS.core.getCSS(css, 'zodbbrowser').then(() => {
			zodbbrowser.hideItemsIfTooMany();
			$('#path a', element).click(function(event) {
				event.stopPropagation();
			});
			$('#path', element).click(zodbbrowser.showGoTo);
			$('#gotoInput', element).blur(zodbbrowser.hideGoTo);
			$('#gotoInput', element).keypress(function(event) {
				if (event.which === 13) { // enter
					zodbbrowser.activateGoTo();
				}
			});
			$('#gotoInput', element).keydown(function(event) {
				if (event.keyCode === 27) { // escape
					zodbbrowser.hideGoTo();
				}
			});
			$(document).keypress(function(event) {
				if (event.which === 103) { // lowercase g
					if ($('#goto', element).is(':hidden')) {
						zodbbrowser.showGoTo();
						event.preventDefault();
					}
				}
			});
			$('input.rollbackbtn', element).click(zodbbrowser.pressRollback);
			$('span.truncated', element).click(function(event) {
				event.preventDefault();
				const
					placeholder = $(this),
					id = placeholder.attr('id');
				$.ajax({
					url: 'zodbbrowser_truncated', data: 'id=' + id,
					success: function(data, status) {
						placeholder.replaceWith(data);
					}
				});
			});
		});
	}
};


if (window.MyAMS) {
	MyAMS.config.modules.push('zodbbrowser');
	MyAMS.zodbbrowser = zodbbrowser;
	console.debug("MyAMS: zodbbrowser module loaded...");
}
