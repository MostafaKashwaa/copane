" Prevent loading twice
if exists('g:loaded_copane')
  finish
endif
let g:loaded_copane = 1

" ============================================================================
" PLUGIN ROOT & VENV PATH (must be set before anything else)
" ============================================================================
let s:plugin_root = expand('<sfile>:p:h:h')
" Default venv now lives inside the plugin, not ~/.vim/copane-venv
let g:copane_venv_dir = get(g:, 'copane_venv_dir', s:plugin_root . '/python/.venv')

" ============================================================================
" CONFIGURATION VARIABLES (with defaults)
" ============================================================================

" Core configuration
let g:copane_python_path = get(g:, 'copane_python_path', 'python3')
let g:copane_default_model = get(g:, 'copane_default_model', 'deepseek-chat')
let g:copane_env_file = get(g:, 'copane_env_file', expand('~/.copane.env'))

" tmux pane configuration
let g:copane_tmux_pane_name = get(g:, 'copane_tmux_pane_name', 'copane')
let g:copane_split_direction = get(g:, 'copane_split_direction', 'vertical')
let g:copane_split_size = get(g:, 'copane_split_size', '33%')
let g:copane_start_command = get(g:, 'copane_start_command', '')
let g:copane_pane_scope = get(g:, 'copane_pane_scope', 'session')
let g:copane_auto_open = get(g:, 'copane_auto_open', 0)

" UI configuration
let g:copane_mapping_prefix = get(g:, 'copane_mapping_prefix', '<leader>t')
let g:copane_show_banner = get(g:, 'copane_show_banner', 1)
let g:copane_debug = get(g:, 'copane_debug', 0)

" Feature flags
let g:copane_enable_ftplugin = get(g:, 'copane_enable_ftplugin', 1)
let g:copane_enable_neovim_async = get(g:, 'copane_enable_neovim_async', 1)
let g:copane_no_suggestions = get(g:, 'copane_no_suggestions', 0)

" ============================================================================
" PREREQUISITE CHECKS
" ============================================================================

function! s:check_prerequisites() abort
  let errors = []

  " Check Python
  if !executable(g:copane_python_path)
    call add(errors, 'Python not found: ' . g:copane_python_path)
  endif

  " Check tmux
  if !executable('tmux')
    call add(errors, 'tmux not found (required)')
    return errors
  endif

  " Check we're inside tmux
  if empty($TMUX)
    call add(errors, 'Not inside a tmux session')
  endif

  return errors
endfunction

" ============================================================================
" PYTHON PATH SETUP (makes `import copane` work)
" ============================================================================

function! s:setup_python_path() abort
  if !isdirectory(g:copane_venv_dir)
    return
  endif

  if has('nvim')
    let l:site_packages = g:copane_venv_dir . '/lib/python*/site-packages'
    let l:matches = glob(l:site_packages, 0, 1)
    if !empty(l:matches)
      let l:pythonpath = getenv('PYTHONPATH')
      let l:selected_site_packages = l:matches[0]
      let $PYTHONPATH = l:selected_site_packages . (empty(l:pythonpath) ? '' : ':' . l:pythonpath)
    endif
  else 
  python3 << EOF
import sys, os
venv_dir = vim.eval('g:copane_venv_dir')
major, minor = sys.version_info[:2]
site_packages = os.path.join(venv_dir, 'lib', f'python{major}.{minor}', 'site-packages')
if os.path.isdir(site_packages) and site_packages not in sys.path:
  sys.path.insert(0, site_packages)
  if int(vim.eval('g:copane_debug')):
    print(f'copane: Added {site_packages} to sys.path')
EOF
  endif

  " For neovim, use system() instead of inline python.
  " if has('nvim')
  "   let l:site-packages = g:copane_venv_dir . '/lib/python*/site-packages'
  "    if isdirectory(glob(l:site-packages))
  "      let l:pythonpath = glob(l:site-packages)
  "      if index(split($PYTHONPATH, ':'), l:pythonpath) < 0
  "        let $PYTHONPATH = l:pythonpath . ':' . $PYTHONPATH
  "        if g:copane_debug
  "          echo 'copane: Added ' . l:pythonpath . ' to PYTHONPATH'
  "        endif
  "      endif
  "    else
  "      if g:copane_debug
  "        echo 'copane: site-packages not found in venv at ' . g:copane_venv_dir
  "      endif
  "    endif
  "    return
  " endif
  "   if g:copane_debug
  "     echo 'copane: Virtual environment not found at ' . g:copane_venv_dir
  "     echo '       Run :CopaneSetupPython or execute setup_python.sh manually.'
  "   endif
  "   return
  " endif

  " Use Vim's own Python to detect its version and build the correct path
"  python3 << EOF
" import sys, os
" venv_dir = vim.eval('g:copane_venv_dir')
" major, minor = sys.version_info[:2]
" site_packages = os.path.join(venv_dir, 'lib', f'python{major}.{minor}', 'site-packages')
" if os.path.isdir(site_packages) and site_packages not in sys.path:
"     sys.path.insert(0, site_packages)
"     if int(vim.eval('g:copane_debug')):
"         print(f'copane: Added {site_packages} to sys.path')
" EOF
endfunction

" ============================================================================
" SETUP
" ============================================================================

function! s:setup() abort
  " Check prerequisites
  let errors = s:check_prerequisites()
  if !empty(errors)
    echohl ErrorMsg
    for error in errors
      echo 'copane: ' . error
    endfor
    echohl None
    return 0
  endif

  " Make the virtual environment available to Python BEFORE loading autoload
  call s:setup_python_path()

  " Load autoload functions (defines tmux_agent#* and the internal functions)
  runtime autoload/tmux_agent.vim

  " Set up filetype plugins if enabled
  if g:copane_enable_ftplugin
    call s:setup_filetype_plugins()
  endif

  " Set up global mappings
  call s:setup_global_mappings()

  " Success message
  if !g:copane_no_suggestions
    echohl MoreMsg
    echo 'copane: Ready! Use :CopaneOpen to start.'
    echohl None
  endif

  return 1
endfunction

function! s:setup_filetype_plugins() abort
  if g:copane_debug
    echo 'copane: Filetype plugins enabled'
  endif
endfunction

function! s:setup_global_mappings() abort
  let prefix = g:copane_mapping_prefix

  " Open/Close/Toggle tmux pane
  execute 'nnoremap <silent> ' . prefix . 'o :CopaneOpen<CR>'
  execute 'nnoremap <silent> ' . prefix . 'c :CopaneClose<CR>'
  execute 'nnoremap <silent> ' . prefix . 't :CopaneToggle<CR>'

  " Send code
  execute 'nnoremap <silent> ' . prefix . 's :CopaneSend<CR>'
  execute 'vnoremap <silent> ' . prefix . 's :CopaneSendVisual<CR>'

  " Model management
  execute 'nnoremap <silent> ' . prefix . 'm :CopaneModelInfo<CR>'
  execute 'nnoremap <silent> ' . prefix . 'M :CopaneListModels<CR>'

  " Config files
  execute 'nnoremap <silent> ' . prefix . 'e :CopaneEditSecrets<CR>'
  execute 'nnoremap <silent> ' . prefix . 'E :CopaneEditConfig<CR>'

  " Help
  execute 'nnoremap <silent> ' . prefix . 'h :CopaneHelp<CR>'

  if g:copane_debug
    echo 'copane: Global mappings configured with prefix: ' . prefix
  endif
endfunction

" ============================================================================
" COMMANDS
" ============================================================================

" Core pane commands
command! -nargs=0 CopaneOpen call tmux_agent#open()
command! -nargs=0 CopaneClose call tmux_agent#close()
command! -nargs=0 CopaneToggle call tmux_agent#toggle()
command! -nargs=* CopaneSend call tmux_agent#send(<f-args>)
" command! -range CopaneSendVisual <line1>,<line2>call tmux_agent#send_visual()
command! -range CopaneSendVisual <line1>,<line2>call tmux_agent#send_visual()

" Model management
command! -nargs=0 CopaneModelInfo call tmux_agent#model_info()
command! -nargs=1 CopaneSwitchModel call tmux_agent#switch_model(<f-args>)
command! -nargs=0 CopaneListModels call tmux_agent#list_models()

" Config file editing
command! -nargs=0 CopaneEditConfig  call copane#edit_model_config()
command! -nargs=0 CopaneEditSecrets call copane#edit_secrets()

" Utility commands
command! -nargs=0 CopaneSetupPython call tmux_agent#setup_python()
command! -nargs=0 CopaneHelp call tmux_agent#help()
command! -nargs=0 CopaneDebug call tmux_agent#debug_info()
command! -nargs=0 CopaneClearHistory call tmux_agent#clear_history()

" Legacy aliases (for backward compatibility)
command! -nargs=0 TmuxAgentOpen CopaneOpen
command! -nargs=0 TmuxAgentClose CopaneClose
command! -nargs=* TmuxAgentSend CopaneSend
command! -range TmuxAgentSendVisual CopaneSendVisual

" ============================================================================
" AUTOCOMMANDS
" ============================================================================

" Initialize on VimEnter (delayed to avoid startup slowdown)
augroup copane_init
  autocmd!
  autocmd VimEnter * call timer_start(100, {-> s:setup()})
augroup END

" Auto-open copane pane for certain filetypes if enabled
if g:copane_auto_open
  augroup copane_auto_open
    autocmd!
    autocmd FileType python,javascript,typescript,go,rust,cpp,java
          \ if !exists('b:copane_auto_opened') |
          \   let b:copane_auto_opened = 1 |
          \   call timer_start(500, {-> tmux_agent#open()}) |
          \ endif
  augroup END
endif

" ============================================================================
" INITIALIZATION MESSAGE
" ============================================================================

" if !g:copane_no_suggestions
"   echohl Comment
"   echo 'copane loaded. Use :CopaneHelp for commands or <leader>to to open.'
"   echohl None
" endif
