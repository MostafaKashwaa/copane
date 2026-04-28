" FileType plugin for JavaScript/TypeScript - copane integration
" This file loads when editing JavaScript or TypeScript files

if exists('b:did_copane_ftplugin_javascript')
  finish
endif
let b:did_copane_ftplugin_javascript = 1

" Only load if copane is available
if !exists('g:loaded_copane')
  finish
endif

" JavaScript-specific configuration
let b:copane_language = 'javascript'
let b:copane_comment_prefix = '//'

" Detect TypeScript
if &filetype == 'typescript' || &filetype == 'typescriptreact'
  let b:copane_language = 'typescript'
endif

" Detect JSX/TSX
if &filetype == 'javascriptreact'
  let b:copane_language = 'jsx'
elseif &filetype == 'typescriptreact'
  let b:copane_language = 'tsx'
endif

" JavaScript-specific key mappings

" Send current line or visual selection to copane
nnoremap <buffer> <silent> <leader>ta :call tmux_agent#send()<CR>
vnoremap <buffer> <silent> <leader>ta :<C-u>call tmux_agent#send_visual()<CR>

" Explain JavaScript/TypeScript code
nnoremap <buffer> <silent> <leader>te :call tmux_agent#send_with_prompt('Explain this ' . b:copane_language . ' code:')<CR>
vnoremap <buffer> <silent> <leader>te :<C-u>call tmux_agent#send_visual_with_prompt('Explain this ' . b:copane_language . ' code:')<CR>

" Generate tests
nnoremap <buffer> <silent> <leader>tt :call tmux_agent#send_with_prompt('Write tests for this ' . b:copane_language . ' code:')<CR>
vnoremap <buffer> <silent> <leader>tt :<C-u>call tmux_agent#send_visual_with_prompt('Write tests for this ' . b:copane_language . ' code:')<CR>
