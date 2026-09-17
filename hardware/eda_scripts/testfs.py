import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
def run(expr, t=25):
    try:
        return ea.js(expr, t=t)
    except Exception as e:
        return "EXC: %s" % e
print("A getProjectsPaths:", run("(async()=>{const R=window._EXTAPI_ROOT_; try{return JSON.stringify(await R.sys_FileSystem.getProjectsPaths());}catch(e){return 'ERR '+String(e&&e.message||e);}})()"))
print("B listProjectsDir:", run("(async()=>{const R=window._EXTAPI_ROOT_; try{const v=await R.sys_FileSystem.listFilesOfFileSystem('C:\\Users\\Admin\\Documents\\LCEDA-Pro\\projects'); return JSON.stringify(v).slice(0,400);}catch(e){return 'ERR '+String(e&&e.message||e);}})()"))
print("C readFile:", run("(async()=>{const R=window._EXTAPI_ROOT_; try{const v=await R.sys_FileSystem.readFileFromFileSystem('C:\\Users\\Admin\\Desktop\\ELF2\\硬件设计\\ELF2_IO_Board.eprj2'); return 'OK '+String(typeof v)+' '+String(v&&(v.name||v.size));}catch(e){return 'ERR '+String(e&&e.message||e);}})()"))
