from typing import AsyncGenerator, Dict, Any, List, Optional
from pathlib import Path
import logging
import ast
import re
from dataclasses import dataclass

from core.base.parsers.base_parser import AsyncParser
from core.base.models import Document, DocumentExtraction

logger = logging.getLogger(__name__)

@dataclass
class HAStructure:
    type: str
    name: str
    details: Dict[str, Any]

@dataclass 
class HAParseResult:
    file_type: str
    structures: List[HAStructure]
    dependencies: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]

class HomeAssistantParser(AsyncParser[Document]):
    """Parser for Home Assistant OS source files"""
    
    def __init__(self, config=None, database_provider=None, llm_provider=None):
        # Store providers if needed
        self.database_provider = database_provider
        self.llm_provider = llm_provider
        self.config = config

        self.patterns = {
            "shell": {
                "function_def": r"^(?:function\s+)?(\w+)\s*\(\)\s*{",
                "variable_assign": r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)$",
                "export": r"^export\s+([A-Z_][A-Z0-9_]*)",
                "if_statement": r"^if\s+\[\s*(.*?)\s*\]\s*;\s*then$",
                "for_loop": r"^for\s+(\w+)\s+in\s+(.*?)\s*;\s*do$",
                "source": r"^\.\s+(.*?)$",
                "command": r"^(mkdir|cp|rm|ln|echo|tar|chmod)\s+"
            },
            "makefile": {
                "package_def": r"^(\w+)_VERSION\s*=\s*(.*)$",
                "package_site": r"^(\w+)_SITE\s*=\s*(.*)$",
                "package_license": r"^(\w+)_LICENSE\s*=\s*(.*)$",
                "package_deps": r"^(\w+)_DEPENDENCIES\s*=\s*(.*)$",
                "eval": r"\$\(eval\s+\$\((.*?)\)\)",
                "variable": r"^([A-Z_][A-Z0-9_]*)\s*[?:]?=\s*(.*?)$"
            },
            "uboot": {
                "env_var": r"setenv\s+(\w+)\s+\"?([^\"]+)\"?",
                "boot_cmd": r"^(boot[zi])\s+(.*)$",
                "load_cmd": r"(fat)?load\s+(\w+)\s+(\$\{.*?\})\s+(\$\{.*?\})\s+(.*)",
                "partition": r"part\s+(start|number)\s+(\$\{.*?\})\s+(\$\{.*?\})\s+(\w+)",
                "conditional": r"if\s+([^;]+);\s*then"
            },
            "config": {
                "config": r"config\s+(\w+)\s*\n\s*(.*?)(?=\n\w|$)",
                "bool": r"bool\s+\"([^\"]+)\"",
                "depends": r"depends\s+on\s+(.+)$",
                "select": r"select\s+(\w+)",
                "help": r"help\s*\n(.*?)(?=\n\w|$)"
            }
        }
        
        # Compile patterns for better performance
        self.compiled_patterns = {}
        for file_type, patterns in self.patterns.items():
            self.compiled_patterns[file_type] = {
                name: re.compile(pattern) 
                for name, pattern in patterns.items()
            }

    async def ingest(self, document: Document, **kwargs) -> AsyncGenerator[DocumentExtraction, None]:
        """Parse Home Assistant OS source files"""
        try:
            # Get file type from extension
            file_type = Path(document.filename).suffix.lower()
            
            # Route to appropriate parser
            parse_result = None
            if file_type == '.mk':
                parse_result = await self._parse_makefile(document.content)
            elif file_type == '.sh':
                parse_result = await self._parse_shell(document.content)
            elif file_type == '.py':
                parse_result = await self._parse_python(document.content)
            elif file_type == '.ush':
                parse_result = await self._parse_uboot_script(document.content)
            elif file_type == '.in':
                parse_result = await self._parse_config_in(document.content)
            elif file_type == '.cfg':
                parse_result = await self._parse_genimage(document.content)
            
            if parse_result:
                yield DocumentExtraction(
                    content=self._format_content(parse_result),
                    metadata={
                        "file_type": parse_result.file_type,
                        "structures": [
                            {
                                "type": s.type,
                                "name": s.name,
                                "details": s.details
                            } 
                            for s in parse_result.structures
                        ],
                        "dependencies": parse_result.dependencies,
                        "relationships": parse_result.relationships
                    }
                )
            else:
                logger.warning(f"Unsupported file type: {file_type}")
                yield DocumentExtraction(
                    content="",
                    metadata={"error": "Unsupported file type"}
                )

        except Exception as e:
            logger.error(f"Error parsing {document.filename}: {str(e)}")
            yield DocumentExtraction(
                content="",
                metadata={"error": str(e)}
            )

    def _format_content(self, parse_result: HAParseResult) -> str:
        """Format parsed content for storage"""
        lines = []
        
        # Add structures
        for struct in parse_result.structures:
            lines.append(f"[{struct.type}] {struct.name}")
            for key, value in struct.details.items():
                lines.append(f"  {key}: {value}")
                
        # Add dependencies
        for dep in parse_result.dependencies:
            lines.append(f"[dependency] {dep.get('type', 'unknown')}")
            for key, value in dep.items():
                if key != 'type':
                    lines.append(f"  {key}: {value}")
                
        return "\n".join(lines)

    async def _parse_shell(self, content: str) -> HAParseResult:
        """Parse shell scripts"""
        structures = []
        dependencies = []
        current_function = None
        
        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            patterns = self.compiled_patterns["shell"]
            
            if match := patterns["function_def"].search(line):
                current_function = match.group(1)
                structures.append(HAStructure(
                    type="function",
                    name=current_function,
                    details={"line": line_num, "commands": []}
                ))
            
            elif match := patterns["variable_assign"].search(line):
                structures.append(HAStructure(
                    type="variable",
                    name=match.group(1),
                    details={
                        "value": match.group(2),
                        "line": line_num,
                        "scope": current_function or "global"
                    }
                ))
            
            elif match := patterns["export"].search(line):
                structures.append(HAStructure(
                    type="export",
                    name=match.group(1),
                    details={
                        "line": line_num,
                        "scope": current_function or "global"
                    }
                ))
            
            elif match := patterns["source"].search(line):
                dependencies.append({
                    "type": "source",
                    "path": match.group(1),
                    "line": line_num
                })

        return HAParseResult(
            file_type="shell",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )

    async def _parse_makefile(self, content: str) -> HAParseResult:
        """Parse Makefile content"""
        structures = []
        dependencies = []
        
        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            patterns = self.compiled_patterns["makefile"]
            
            if match := patterns["package_def"].search(line):
                structures.append(HAStructure(
                    type="package_version",
                    name=match.group(1),
                    details={
                        "version": match.group(2),
                        "line": line_num
                    }
                ))
            
            elif match := patterns["package_deps"].search(line):
                deps = [d.strip() for d in match.group(2).split()]
                for dep in deps:
                    dependencies.append({
                        "from": match.group(1),
                        "to": dep,
                        "type": "package_dependency"
                    })
            
            elif match := patterns["eval"].search(line):
                structures.append(HAStructure(
                    type="eval",
                    name=match.group(1),
                    details={
                        "line": line_num,
                        "full_eval": match.group(0)
                    }
                ))

        return HAParseResult(
            file_type="makefile",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )

    async def _parse_python(self, content: str) -> HAParseResult:
        """Parse Python files"""
        structures = []
        dependencies = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    structures.append(HAStructure(
                        type="function",
                        name=node.name,
                        details={
                            "args": [arg.arg for arg in node.args.args],
                            "decorators": [d.id for d in node.decorator_list if isinstance(d, ast.Name)]
                        }
                    ))
                
                elif isinstance(node, ast.ClassDef):
                    structures.append(HAStructure(
                        type="class",
                        name=node.name,
                        details={
                            "bases": [base.id for base in node.bases if isinstance(base, ast.Name)],
                            "methods": [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
                        }
                    ))
                
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            dependencies.append({
                                "type": "import",
                                "name": name.name
                            })
                    else:
                        dependencies.append({
                            "type": "import_from",
                            "module": node.module,
                            "names": [n.name for n in node.names]
                        })
                    
        except SyntaxError:
            structures.append(HAStructure(
                type="error",
                name="syntax_error",
                details={"message": "Invalid Python syntax"}
            ))

        return HAParseResult(
            file_type="python",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )

    async def _parse_uboot_script(self, content: str) -> HAParseResult:
        """Parse U-Boot script files"""
        structures = []
        dependencies = []
        
        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            patterns = self.compiled_patterns["uboot"]
            
            if match := patterns["env_var"].search(line):
                structures.append(HAStructure(
                    type="uboot_env",
                    name=match.group(1),
                    details={
                        "value": match.group(2),
                        "line": line_num
                    }
                ))
            
            elif match := patterns["boot_cmd"].search(line):
                structures.append(HAStructure(
                    type="boot_command",
                    name=match.group(1),
                    details={
                        "parameters": match.group(2),
                        "line": line_num
                    }
                ))
            
            elif match := patterns["load_cmd"].search(line):
                structures.append(HAStructure(
                    type="load_command",
                    name=match.group(1) or "load",
                    details={
                        "device": match.group(2),
                        "address": match.group(3),
                        "file": match.group(5),
                        "line": line_num
                    }
                ))

        return HAParseResult(
            file_type="uboot_script",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )

    async def _parse_config_in(self, content: str) -> HAParseResult:
        """Parse Config.in files"""
        structures = []
        dependencies = []
        patterns = self.compiled_patterns["config"]
        
        for match in patterns["config"].finditer(content):
            config_name = match.group(1)
            config_body = match.group(2)
            
            details = {"type": "unknown"}
            
            if bool_match := patterns["bool"].search(config_body):
                details["type"] = "bool"
                details["prompt"] = bool_match.group(1)
            
            if depends_match := patterns["depends"].search(config_body):
                dependencies.append({
                    "from": config_name,
                    "to": depends_match.group(1),
                    "type": "depends"
                })
            
            if help_match := patterns["help"].search(config_body):
                details["help"] = help_match.group(1).strip()
            
            structures.append(HAStructure(
                type="config_option",
                name=config_name,
                details=details
            ))

        return HAParseResult(
            file_type="config_in",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )

    async def _parse_genimage(self, content: str) -> HAParseResult:
        """Parse genimage configuration files"""
        structures = []
        dependencies = []
        
        patterns = {
            "image_def": r"^image\s+([\"'].*?[\"']|\S+)\s*{",
            "size": r"^\s*size\s*=\s*([\"'].*?[\"']|\S+)",
            "include": r"^\s*include\([\"'](.*?)[\"']\)"
        }
        
        current_image = None
        
        for line_num, line in enumerate(content.splitlines(), 1):
            if match := re.search(patterns["image_def"], line):
                current_image = match.group(1).strip('"\'')
                structures.append(HAStructure(
                    type="image",
                    name=current_image,
                    details={"line": line_num, "properties": {}}
                ))
            
            elif match := re.search(patterns["size"], line) and current_image:
                for struct in structures:
                    if struct.name == current_image:
                        struct.details["properties"]["size"] = match.group(1).strip('"\'')
            
            elif match := re.search(patterns["include"], line):
                structures.append(HAStructure(
                    type="include",
                    name=match.group(1),
                    details={"line": line_num}
                ))

        return HAParseResult(
            file_type="genimage",
            structures=structures,
            dependencies=dependencies,
            relationships=[]
        )