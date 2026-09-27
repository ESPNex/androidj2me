# ProGuard's microedition mode adds the CLDC StackMap verification attributes.
# Paths are relative to this file, at the root of NokiaE63_MIDP.
-injars build/raw.jar
-outjars build/preverified.jar
-libraryjars toolchain/cldc.jar
-libraryjars toolchain/midp.jar
-microedition
-dontshrink
-dontoptimize
-dontobfuscate
-keepattributes Exceptions,SourceFile,LineNumberTable
-keep class * { *; }
